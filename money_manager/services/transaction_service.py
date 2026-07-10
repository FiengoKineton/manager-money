from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any, Mapping

import pandas as pd

from money_manager.services.account_payment_policy_service import (
    BALANCE_INSUFFICIENT_ANOTHER_CARD,
    BALANCE_INSUFFICIENT_CREDIT,
    BALANCE_INSUFFICIENT_STOP,
    BALANCE_METHOD_ANOTHER_CARD,
    BALANCE_METHOD_BALANCE,
    BALANCE_METHOD_CREDIT,
    payment_selection_from_form,
    resolve_payment_selection,
)

from money_manager.config import (
    CREDIT_ACCOUNT_KEYWORDS,
    CREDIT_CARD_DUE_DAY,
    MAIN_ACCOUNT_KEY,
    MAIN_NET_AFFECTS,
    MAIN_NET_CREDIT_PENDING,
    PAYPAL_ACCOUNT_KEY,
    account_due_day_for_key,
    PAYPAL_CREDIT_ACCOUNT_VALUE,
    TRANSACTION_TYPES,
    account_label_for_key,
    account_policy_for_key,
    auxiliary_account_keys,
    normalize_account_key,
)
from money_manager.domain.transaction import TransactionInput, make_transaction_uid
from money_manager.services.account_config_service import configured_account_key
from money_manager.services.currency_service import append_conversion_note, convert_amount_to_eur
from money_manager.services.category_icon_service import icon_for_category, load_category_icons_config
from money_manager.repositories.pending import append_pending
from money_manager.repositories.transactions import (
    append_transaction,
    delete_transaction,
    load_all,
    transaction_has_payment_snapshots,
    transaction_is_legacy_payment,
    transaction_row_to_payment_context,
    update_transaction,
)
from money_manager.services.account_ledger_service import (
    append_adjustment_rows_for_transaction,
    append_ledger_movements,
    ledger_rows_for_transaction,
    rows_from_payment_resolution,
    void_ledger_for_transaction,
)
from money_manager.services.payment_routing_service import resolve_payment, resolution_json_dumps

# Backwards-compatible names used by templates/forms.
PAYPAL_METHOD_BALANCE = BALANCE_METHOD_BALANCE
PAYPAL_METHOD_CREDIT = BALANCE_METHOD_CREDIT
PAYPAL_METHOD_ANOTHER_CARD = BALANCE_METHOD_ANOTHER_CARD
PAYPAL_INSUFFICIENT_STOP = BALANCE_INSUFFICIENT_STOP
PAYPAL_INSUFFICIENT_ANOTHER_CARD = BALANCE_INSUFFICIENT_ANOTHER_CARD
PAYPAL_INSUFFICIENT_CREDIT = BALANCE_INSUFFICIENT_CREDIT

PAYMENT_AFFECTING_FIELDS = {"date", "amount", "account", "account_id", "payment_method", "payment_method_id"}
SETTLED_LEDGER_STATUSES = {"settled", "executed", "reconciled"}


def next_credit_due(payment_date=None, due_day: int = CREDIT_CARD_DUE_DAY) -> date:
    payment_date = payment_date or date.today()

    if payment_date.month == 12:
        return date(payment_date.year + 1, 1, due_day)

    return date(payment_date.year, payment_date.month + 1, due_day)


def save_new_transaction(tx_input: TransactionInput) -> dict:
    """Save a new transaction and return a small UI-friendly result.

    Prompt 11D adds an opt-in ledger route. Forms that submit stable
    ``payment_method_id`` or ``account_id`` use the ledger-backed path. Old v10
    forms still use the existing pending/balance router until Prompt 11F migrates
    all forms.
    """
    tx = _transaction_payload_in_eur(tx_input)
    if tx_input.account_id:
        tx["account_id"] = tx_input.account_id
    if tx_input.payment_method_id:
        tx["payment_method_id"] = tx_input.payment_method_id
    if tx_input.payment_channel_method_id:
        tx["payment_channel_method_id"] = tx_input.payment_channel_method_id

    return save_transaction_payload(
        tx,
        payment_method=tx_input.account_payment_method or tx_input.paypal_payment_method,
        insufficient_action=tx_input.account_insufficient_action or tx_input.paypal_insufficient_action,
        due_date=_due_date_from_input(tx_input),
        account_id=tx_input.account_id,
        payment_method_id=tx_input.payment_method_id,
    )


def save_transaction_payload(
    tx: dict,
    payment_method: str | None = None,
    insufficient_action: str | None = None,
    due_date: date | None = None,
    account_id: str | None = None,
    payment_method_id: str | None = None,
) -> dict:
    """Save an already-normalized transaction dict.

    Stable Prompt 11D ids use the professional ledger route. Legacy callers that
    do not pass stable ids continue through the v10 router so old forms and
    external modules remain compatible.
    """
    tx = dict(tx)
    # Rule-based automation is deliberately soft: it only fills blank category/link
    # fields and never changes amounts, dates, accounts or payment routing.
    try:
        from money_manager.services.smart_rule_service import apply_smart_rules_to_transaction

        tx = apply_smart_rules_to_transaction(tx)
    except Exception:
        pass

    explicit_account_id = _first_nonblank(account_id, tx.get("account_id"))
    explicit_payment_method_id = _first_nonblank(payment_method_id, tx.get("payment_method_id"))
    if explicit_account_id:
        tx["account_id"] = explicit_account_id
    if explicit_payment_method_id:
        tx["payment_method_id"] = explicit_payment_method_id

    if explicit_payment_method_id or explicit_account_id:
        routed = _save_transaction_with_ledger_payload(tx)
        # Explicit payment-method selections should fail visibly if routing is
        # invalid. For account-only hints, fall back to v10 if routing is unsafe.
        if routed.get("ok") or explicit_payment_method_id:
            return routed

    account_raw = str(tx.get("account", "") or "").strip()
    account_key = normalize_account_key(account_raw)
    tx_type = str(tx.get("type", "") or "").casefold()
    explicit_due_date = due_date

    if tx_type == "expense" and account_key in auxiliary_account_keys():
        policy = account_policy_for_key(account_key)
        if policy == MAIN_NET_AFFECTS:
            tx_id = append_transaction(tx)
            return {"ok": True, "message": "Transaction saved and included in main net by this account policy.", "transaction_ids": [tx_id], "pending_ids": []}
        if policy == MAIN_NET_CREDIT_PENDING:
            return _save_credit_account_charge(tx, account_key=account_key)
        selection = resolve_payment_selection(
            account_key,
            payment_method=payment_method,
            insufficient_action=insufficient_action,
        )
        return _save_balance_account_expense(
            tx,
            account_key=account_key,
            method=selection["payment_method"],
            insufficient_action=selection["insufficient_action"],
            due=explicit_due_date or _due_date_from_payload(tx),
        )

    if tx_type == "expense" and account_raw.casefold() in CREDIT_ACCOUNT_KEYWORDS:
        tx["account"] = "credit"
        pending_id = append_pending(tx, explicit_due_date or _due_date_from_payload(tx))
        return {"ok": True, "message": "Credit-card payment added to pending.", "transaction_ids": [], "pending_ids": [pending_id] if pending_id is not None else []}

    tx_id = append_transaction(tx)
    return {"ok": True, "message": "Transaction saved.", "transaction_ids": [tx_id], "pending_ids": []}


def _sync_credit_settlements_if_needed(ledger_rows: list[dict[str, Any]] | None, *, force: bool = False) -> None:
    if not force and not any(str(row.get("movement_kind") or "") == "credit_liability_increase" for row in (ledger_rows or [])):
        return
    try:
        from money_manager.services.credit_settlement_service import sync_credit_settlements

        sync_credit_settlements(sync_pending=True)
    except Exception:
        # Settlement sync is a derived view.  The transaction and ledger save must
        # remain successful even if the pending mirror cannot be refreshed in the
        # same request.
        pass


def _save_transaction_with_ledger_payload(tx: Mapping[str, Any]) -> dict:
    tx = dict(tx)
    tx_type = str(tx.get("type") or "").casefold()
    account_hint = _account_hint_for_resolution(tx)
    method_id = _first_nonblank(tx.get("payment_method_id"), tx.get("payment_channel_method_id"))
    amount = _to_float(tx.get("amount"))
    resolution = resolve_payment(
        tx_type,
        amount,
        tx.get("date") or date.today().isoformat(),
        account_id=account_hint or None,
        payment_method_id=method_id or None,
        category=tx.get("category"),
        sub_category=tx.get("sub_category"),
        description=str(tx.get("description") or ""),
        existing_row=tx,
    )
    if not resolution.ok:
        return {"ok": False, "error": "; ".join(resolution.errors) or "Payment route could not be resolved.", "warnings": resolution.warnings}

    tx.update(_transaction_metadata_from_resolution(tx, resolution))
    tx_id = append_transaction(tx)
    uid = make_transaction_uid(tx_type, tx_id)
    ledger_rows = rows_from_payment_resolution(
        resolution,
        transaction_uid=uid,
        transaction_type=tx_type,
        transaction_id=str(tx_id),
        source_kind="transaction_save",
        source_id=str(tx_id),
    )
    ledger_ids = append_ledger_movements(ledger_rows) if ledger_rows else []
    _sync_credit_settlements_if_needed(ledger_rows)
    if ledger_rows:
        update_transaction(tx_id, tx_type, {"transaction_uid": uid, "ledger_group_id": resolution.ledger_group_id, "ledger_status": "posted"})
    return {
        "ok": True,
        "message": resolution.display_explanation or "Transaction saved with payment route.",
        "transaction_ids": [tx_id],
        "pending_ids": [],
        "ledger_ids": ledger_ids,
        "ledger_group_id": resolution.ledger_group_id,
        "warnings": resolution.warnings,
    }


def account_balance(account_key: str) -> float:
    """Current balance of any auxiliary account."""
    from money_manager.services.account_service import account_balance_rows

    key = normalize_account_key(account_key)
    rows = account_balance_rows(load_transactions())
    for row in rows:
        if row.get("key") == key:
            return float(row.get("balance", 0.0) or 0.0)
    return 0.0


def account_balances_for_preview() -> dict:
    from money_manager.services.account_service import account_balance_rows

    return {row.get("key"): float(row.get("balance", 0.0) or 0.0) for row in account_balance_rows(load_transactions())}


def main_net_for_preview() -> float:
    from money_manager.services.account_service import main_account_transactions

    df = main_account_transactions(load_transactions())
    if df.empty:
        return 0.0
    return float(df.get("signed_amount", 0).sum())


def paypal_balance() -> float:
    """Current balance of the legacy PayPal auxiliary account, if this user configured one."""
    return account_balance(PAYPAL_ACCOUNT_KEY)


def _save_balance_account_expense(tx: dict, account_key: str, method: str, insufficient_action: str, due: date) -> dict:
    account_label = account_label_for_key(account_key)
    method = str(method or BALANCE_METHOD_BALANCE).casefold()

    if method == BALANCE_METHOD_CREDIT:
        pending_id = _append_balance_credit_pending(tx, due, account_label=account_label, account_key=account_key)
        return {"ok": True, "message": f"{account_label} checkout added to pending credit.", "transaction_ids": [], "pending_ids": [pending_id] if pending_id is not None else []}

    if method == BALANCE_METHOD_ANOTHER_CARD:
        main_tx = _with_note(tx, f"{account_label} checkout paid with another card/main bank route.")
        main_tx["account"] = ""
        tx_id = append_transaction(main_tx)
        return {"ok": True, "message": f"{account_label} checkout saved as a main-bank/card expense.", "transaction_ids": [tx_id], "pending_ids": []}

    amount = float(tx.get("amount", 0.0) or 0.0)
    balance = account_balance(account_key)
    if amount <= balance + 0.005:
        balance_tx = _with_note(tx, f"Paid from {account_label} balance.")
        balance_tx["account"] = account_label
        tx_id = append_transaction(balance_tx)
        return {"ok": True, "message": f"{account_label} balance expense saved.", "transaction_ids": [tx_id], "pending_ids": []}

    usable_balance = max(balance, 0.0)
    remaining = max(0.0, amount - usable_balance)
    action = str(insufficient_action or BALANCE_INSUFFICIENT_STOP).casefold()
    tx_ids: list[int] = []
    pending_ids: list[int] = []

    if action == BALANCE_INSUFFICIENT_ANOTHER_CARD:
        if usable_balance > 0.005:
            tx_ids.append(append_transaction(_balance_account_part(tx, usable_balance, amount, account_label)))
        main_tx = _with_amount(tx, remaining)
        main_tx = _with_note(main_tx, f"Remaining {account_label} checkout paid with another card/main bank route after using € {usable_balance:.2f} {account_label} balance.")
        main_tx["account"] = ""
        tx_ids.append(append_transaction(main_tx))
        return {"ok": True, "message": f"{account_label} balance used and remaining amount saved as main-bank/card expense.", "transaction_ids": tx_ids, "pending_ids": []}

    if action == BALANCE_INSUFFICIENT_CREDIT:
        if usable_balance > 0.005:
            tx_ids.append(append_transaction(_balance_account_part(tx, usable_balance, amount, account_label)))
        pending_tx = _with_amount(tx, remaining)
        pending_tx = _with_note(pending_tx, f"Remaining {account_label} checkout scheduled on credit after using € {usable_balance:.2f} {account_label} balance.")
        pending_id = _append_balance_credit_pending(pending_tx, due, account_label=account_label, account_key=account_key)
        if pending_id is not None:
            pending_ids.append(pending_id)
        return {"ok": True, "message": f"{account_label} balance used and remaining amount added to pending credit.", "transaction_ids": tx_ids, "pending_ids": pending_ids}

    return {
        "ok": False,
        "error": (
            f"{account_label} balance is not enough: available € {balance:.2f}, "
            f"expense € {amount:.2f}, missing € {remaining:.2f}. "
            "Choose another payment method or choose how to split the remaining amount."
        ),
        "account_key": account_key,
        "account_balance": balance,
        "account_missing": remaining,
    }


def _save_credit_account_charge(tx: dict, account_key: str) -> dict:
    """Log a credit-card purchase now and aggregate settlement separately."""
    from money_manager.services.pending_service import sync_credit_account_statements

    account_label = account_label_for_key(account_key)
    credit_tx = _with_note(tx, f"Paid with {account_label}; statement settlement is grouped in Pending.")
    credit_tx["account"] = account_key
    tx_id = append_transaction(credit_tx)
    try:
        sync_credit_account_statements()
    except Exception:
        pass
    return {
        "ok": True,
        "message": f"{account_label} credit purchase saved. It will be grouped by statement month in Pending.",
        "transaction_ids": [tx_id],
        "pending_ids": [],
    }


def _append_balance_credit_pending(tx: dict, due: date, account_label: str, account_key: str) -> int | None:
    pending_tx = _with_note(tx, f"{account_label} checkout scheduled through credit/card route.")
    pending_tx["account"] = PAYPAL_CREDIT_ACCOUNT_VALUE if account_key == PAYPAL_ACCOUNT_KEY else "credit"
    return append_pending(pending_tx, due)


def _balance_account_part(tx: dict, balance: float, original_amount: float, account_label: str) -> dict:
    part = _with_amount(tx, max(balance, 0.0))
    part = _with_note(part, f"Partial {account_label} balance payment for € {original_amount:.2f} checkout.")
    part["account"] = account_label
    return part


# Backwards-compatible helpers kept for older imports/tests.
def _save_paypal_expense(tx: dict, tx_input: TransactionInput) -> dict:
    return _save_balance_account_expense(
        tx,
        account_key=PAYPAL_ACCOUNT_KEY,
        method=tx_input.account_payment_method or tx_input.paypal_payment_method or BALANCE_METHOD_BALANCE,
        insufficient_action=tx_input.account_insufficient_action or tx_input.paypal_insufficient_action or BALANCE_INSUFFICIENT_STOP,
        due=_due_date_from_input(tx_input),
    )


def _append_paypal_credit_pending(tx: dict, due: date) -> None:
    _append_balance_credit_pending(tx, due, account_label="PayPal", account_key=PAYPAL_ACCOUNT_KEY)


def _paypal_balance_part(tx: dict, balance: float, original_amount: float) -> dict:
    return _balance_account_part(tx, balance, original_amount, "PayPal")


def _with_amount(tx: dict, amount: float) -> dict:
    updated = dict(tx)
    updated["amount"] = round(float(amount or 0.0), 2)
    return updated


def _with_note(tx: dict, note: str) -> dict:
    updated = dict(tx)
    description = str(updated.get("description", "") or "").strip()
    updated["description"] = f"{description} [{note}]" if description else note
    return updated


def _due_date_from_input(tx_input: TransactionInput) -> date:
    try:
        payment_date = date.fromisoformat(tx_input.date)
    except (TypeError, ValueError):
        payment_date = date.today()
    account_key = normalize_account_key(tx_input.account_id or tx_input.account)
    due_day = account_due_day_for_key(account_key, CREDIT_CARD_DUE_DAY) if account_policy_for_key(account_key) == MAIN_NET_CREDIT_PENDING else CREDIT_CARD_DUE_DAY
    return next_credit_due(payment_date, due_day=due_day)


def _transaction_payload_in_eur(tx_input: TransactionInput) -> dict:
    tx = tx_input.as_dict()
    conversion = convert_amount_to_eur(tx_input.amount, tx_input.currency)
    tx["amount"] = conversion["amount_eur"]
    tx["description"] = append_conversion_note(tx_input.description, conversion)

    if conversion.get("is_conversion"):
        tx["original_amount"] = f"{conversion['original_amount']:.2f}"
        tx["original_currency"] = conversion["original_currency"]
        tx["exchange_rate_to_eur"] = f"{conversion['rate_to_eur']:.8f}"
        tx["exchange_correction_to_eur"] = f"{conversion['correction_to_eur']:.8f}"
        tx["exchange_effective_rate_to_eur"] = f"{conversion['effective_rate_to_eur']:.8f}"
    else:
        tx["original_amount"] = ""
        tx["original_currency"] = "EUR"
        tx["exchange_rate_to_eur"] = "1.00000000"
        tx["exchange_correction_to_eur"] = "0.00000000"
        tx["exchange_effective_rate_to_eur"] = "1.00000000"
    tx.pop("currency", None)
    return tx


def _due_date_from_payload(tx: dict, due_day: int = CREDIT_CARD_DUE_DAY) -> date:
    try:
        payment_date = date.fromisoformat(str(tx.get("date", "") or ""))
    except (TypeError, ValueError):
        payment_date = date.today()
    return next_credit_due(payment_date, due_day=due_day)


def load_transactions() -> pd.DataFrame:
    from money_manager.services.cache_service import cached_calculation

    return cached_calculation("transactions.load_all", load_all)


def prepare_transactions_for_display(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if df.empty:
        df["date_str"] = []
        df["amount_str"] = []
        df["row_index"] = []
        df["category_icon"] = []
        df["account_display"] = []
        df["account_icon"] = []
        return df

    for column in [
        "account",
        "account_id",
        "account_key",
        "account_key_snapshot",
        "account_label",
        "account_name_snapshot",
        "payment_method",
        "payment_method_id",
        "ledger_status",
        "contact_id",
        "contact_name",
        "iban_snapshot",
        "bic_swift_snapshot",
        "bank_name_snapshot",
        "transfer_reference",
        "transfer_status",
    ]:
        if column not in df.columns:
            df[column] = ""
        df[column] = df[column].fillna("")

    df["date_str"] = df["date"].dt.strftime("%Y-%m-%d")
    df["amount_str"] = df["amount"].map(lambda amount: f"{amount:.2f}")
    df["row_index"] = df.index
    icon_config = load_category_icons_config()
    df["category_icon"] = df.apply(
        lambda row: icon_for_category(row.get("category", ""), row.get("type", ""), config=icon_config),
        axis=1,
    )
    account_icons = _account_icon_lookup_for_display()
    account_views = df.apply(lambda row: _transaction_account_display_fields(row, account_icons), axis=1)
    if not account_views.empty:
        account_view_df = pd.DataFrame(account_views.tolist(), index=df.index)
        for column in ["account_display", "account_icon", "account_key_display"]:
            df[column] = account_view_df[column]
    else:
        df["account_display"] = ""
        df["account_icon"] = "🏦"
        df["account_key_display"] = MAIN_ACCOUNT_KEY
    df["delay_date_default"] = (date.today() + timedelta(days=1)).isoformat()
    return df


def _account_icon_lookup_for_display() -> dict[str, str]:
    lookup = {MAIN_ACCOUNT_KEY: "🏦"}
    try:
        from money_manager.services.account_config_service import all_accounts

        for account in all_accounts(include_archived=True, include_main=True):
            key = str(account.get("key") or account.get("id") or "").strip()
            icon = str(account.get("icon") or "").strip()[:12]
            if key and icon:
                lookup[key] = icon
    except Exception:
        pass
    return lookup


def _fallback_account_icon_for_display(key: str, label: str) -> str:
    text = f"{key} {label}".casefold()
    if "paypal" in text:
        return "🅿️"
    if "revolut" in text or "revoulout" in text:
        return "🇷"
    if "edenred" in text or "ticket restaurant" in text:
        return "🍽️"
    if "cash" in text or "contanti" in text:
        return "💶"
    if "credit" in text or "card" in text or "carta" in text:
        return "💳"
    if "chatgpt" in text or "chatgbt" in text or "openai" in text:
        return "🤖"
    return "🏦"


def _transaction_account_display_fields(row: Mapping[str, Any], icon_lookup: Mapping[str, str]) -> dict[str, str]:
    raw_account = _clean_display(row.get("account", ""))
    account_id = _clean_display(row.get("account_id", ""))
    key_snapshot = _clean_display(row.get("account_key", "") or row.get("account_key_snapshot", ""))
    snapshot_label = _clean_display(row.get("account_name_snapshot", "") or row.get("account_label", ""))
    source_value = account_id or key_snapshot or raw_account

    try:
        key = normalize_account_key(source_value)
    except Exception:
        key = MAIN_ACCOUNT_KEY
    key = key or MAIN_ACCOUNT_KEY

    try:
        configured_label = account_label_for_key(key)
    except Exception:
        configured_label = "Mediolanum" if key == MAIN_ACCOUNT_KEY else key.replace("_", " ").title()

    label = snapshot_label or configured_label or raw_account
    cleaned_label = str(label or "").strip()
    if not cleaned_label or cleaned_label.casefold() in {"main_bank", "main bank", "primary current account", "bank account"}:
        cleaned_label = configured_label or "Mediolanum"

    # Keep truly custom text if the account cannot be mapped, but never show raw
    # stable IDs like ``main_bank`` in the transaction table.
    if raw_account and key == MAIN_ACCOUNT_KEY and raw_account.casefold() not in {"", "auto", "bank", "main", "main_bank", "main bank", "bank account", "conto", "conto corrente"}:
        cleaned_label = configured_label or raw_account

    icon = str(icon_lookup.get(key) or _fallback_account_icon_for_display(key, cleaned_label)).strip()[:12] or "🏦"
    return {
        "account_display": cleaned_label,
        "account_icon": icon,
        "account_key_display": key,
    }


def transaction_detail_context(row_index: int) -> tuple[dict, list[str]]:
    from money_manager.config import categories_for

    df = load_transactions()

    try:
        row = df.loc[row_index]
    except KeyError as exc:
        raise LookupError(f"Transaction {row_index} not found") from exc

    raw = _plain_row(row)
    tx_type = str(raw.get("type", ""))
    csv_id = str(raw.get("id", ""))
    uid = raw.get("transaction_uid") or make_transaction_uid(tx_type, csv_id)
    ledger_rows = ledger_rows_for_transaction(uid, include_void=True) if uid else []
    route_explanation = _route_explanation_from_row(raw, ledger_rows)
    active_ledger_rows = [ledger for ledger in ledger_rows if not _truthy(ledger.get("is_void")) and str(ledger.get("status") or "") != "voided"]

    tx = {
        "id": int(row_index),
        "csv_id": int(float(csv_id)) if str(csv_id).replace('.', '', 1).isdigit() else csv_id,
        "transaction_uid": uid,
        "type": tx_type,
        "date": _date_str(raw.get("date")),
        "category": _clean_display(raw.get("category", "")),
        "sub_category": _clean_display(raw.get("sub_category", "")),
        "amount": f"{_to_float(raw.get('amount')):.2f}",
        "original_amount": _clean_display(raw.get("original_amount", "")),
        "original_currency": _clean_display(raw.get("original_currency", "")),
        "exchange_rate_to_eur": _clean_display(raw.get("exchange_rate_to_eur", "")),
        "exchange_correction_to_eur": _clean_display(raw.get("exchange_correction_to_eur", "")),
        "exchange_effective_rate_to_eur": _clean_display(raw.get("exchange_effective_rate_to_eur", "")),
        "account": _clean_display(raw.get("account", "")),
        "account_id": _clean_display(raw.get("account_id", "")),
        "account_key": _clean_display(raw.get("account_key", normalize_account_key(raw.get("account", "")))),
        "account_label": _clean_display(raw.get("account_label", "")),
        "account_name_snapshot": _clean_display(raw.get("account_name_snapshot", "")),
        "payment_method": _clean_display(raw.get("payment_method", "")),
        "payment_method_id": _clean_display(raw.get("payment_method_id", "")),
        "payment_method_name_snapshot": _clean_display(raw.get("payment_method_name_snapshot", "")),
        "payment_channel_method_id_snapshot": _clean_display(raw.get("payment_channel_method_id_snapshot", "")),
        "payment_channel_name_snapshot": _clean_display(raw.get("payment_channel_name_snapshot", "")),
        "funding_account_id_snapshot": _clean_display(raw.get("funding_account_id_snapshot", "")),
        "funding_account_name_snapshot": _clean_display(raw.get("funding_account_name_snapshot", "")),
        "settlement_account_id_snapshot": _clean_display(raw.get("settlement_account_id_snapshot", "")),
        "settlement_account_name_snapshot": _clean_display(raw.get("settlement_account_name_snapshot", "")),
        "liability_account_id_snapshot": _clean_display(raw.get("liability_account_id_snapshot", "")),
        "liability_account_name_snapshot": _clean_display(raw.get("liability_account_name_snapshot", "")),
        "settlement_mode_snapshot": _clean_display(raw.get("settlement_mode_snapshot", "")),
        "payment_due_date_snapshot": _clean_display(raw.get("payment_due_date_snapshot", "")),
        "payment_due_day_snapshot": _clean_display(raw.get("payment_due_day_snapshot", "")),
        "payment_statement_period_snapshot": _clean_display(raw.get("payment_statement_period_snapshot", "")),
        "payment_resolution_json": _clean_display(raw.get("payment_resolution_json", "")),
        "ledger_group_id": _clean_display(raw.get("ledger_group_id", "")),
        "ledger_status": _clean_display(raw.get("ledger_status", "")) or ("posted" if active_ledger_rows else "legacy/no ledger"),
        "ledger_rows": ledger_rows,
        "active_ledger_count": len(active_ledger_rows),
        "payment_routing_explanation": route_explanation,
        "is_legacy_payment": transaction_is_legacy_payment(raw),
        "contact_id": _clean_display(raw.get("contact_id", "")),
        "contact_name": _clean_display(raw.get("contact_name", "")),
        "iban_snapshot": _clean_display(raw.get("iban_snapshot", "")),
        "bic_swift_snapshot": _clean_display(raw.get("bic_swift_snapshot", "")),
        "bank_name_snapshot": _clean_display(raw.get("bank_name_snapshot", "")),
        "transfer_reference": _clean_display(raw.get("transfer_reference", "")),
        "transfer_status": _clean_display(raw.get("transfer_status", "")),
        "linked_object_type": _clean_display(raw.get("linked_object_type", "")),
        "linked_object_id": _clean_display(raw.get("linked_object_id", "")),
        "linked_object_name": _clean_display(raw.get("linked_object_name", "")),
        "description": _clean_display(raw.get("description", "")),
        "created_at": _clean_display(raw.get("created_at", "")),
        "delay_date_default": (date.today() + timedelta(days=1)).isoformat(),
    }

    try:
        from money_manager.services.receipt_service import receipt_for_transaction

        tx["receipt"] = receipt_for_transaction(tx)
    except Exception:
        tx["receipt"] = {}

    try:
        from money_manager.services.timeline_service import transaction_link_summary

        tx["linked_object"] = transaction_link_summary(tx)
    except Exception:
        tx["linked_object"] = {}

    return tx, categories_for(tx["type"])


def delay_existing_transaction(row_index: int, new_date: str) -> dict:
    if not new_date:
        return {"ok": False, "error": "Missing delay date."}

    df = load_transactions()
    row = df.loc[row_index]
    raw = _plain_row(row)
    form = {
        "type": raw.get("type", "expense"),
        "date": new_date,
        "category": raw.get("category", ""),
        "sub_category": raw.get("sub_category", ""),
        "amount": raw.get("amount", "0"),
        "account": raw.get("account", ""),
        "account_id": raw.get("account_id", ""),
        "payment_method_id": raw.get("payment_method_id", ""),
        "description": raw.get("description", ""),
        "force_payment_rebuild": "1" if transaction_has_payment_snapshots(raw) else "",
    }
    return update_existing_transaction(row_index, form)


def update_existing_transaction(row_index: int, form) -> dict:
    df = load_transactions()
    row = df.loc[row_index]
    original = _plain_row(row)
    tx_input = TransactionInput.from_form({**form, "type": original.get("type", "")})

    data = {
        "date": tx_input.date,
        "category": tx_input.category,
        "sub_category": tx_input.sub_category,
        "amount": tx_input.amount,
        "account": tx_input.account,
        "description": tx_input.description,
    }

    selected_account_id = ""
    if tx_input.account_id:
        selected_account_id = configured_account_key(tx_input.account_id) or ""
        if not selected_account_id:
            return {"ok": False, "error": f"Unknown or inactive account: {tx_input.account_id}"}
        # Persist the stable selection even for old CSV-only transactions.  The
        # old edit path updated only the legacy text field, so the detail screen
        # could show the new snapshot while account calculations still used the
        # previous account.
        data.update({
            "account_id": selected_account_id,
            "account_key_snapshot": selected_account_id,
            "account_name_snapshot": account_label_for_key(selected_account_id),
            "account": "" if selected_account_id == MAIN_ACCOUNT_KEY else selected_account_id,
        })

    # The transaction detail screen edits the already-saved EUR value. The add
    # screen has the currency selector and passes currency explicitly, so only
    # re-run conversion when that field is present.
    if "currency" in form:
        converted = _transaction_payload_in_eur(tx_input)
        data.update({
            "amount": converted["amount"],
            "description": converted["description"],
            "original_amount": converted.get("original_amount", ""),
            "original_currency": converted.get("original_currency", ""),
            "exchange_rate_to_eur": converted.get("exchange_rate_to_eur", ""),
            "exchange_correction_to_eur": converted.get("exchange_correction_to_eur", ""),
            "exchange_effective_rate_to_eur": converted.get("exchange_effective_rate_to_eur", ""),
        })

    original_uid = original.get("transaction_uid") or make_transaction_uid(original.get("type", ""), original.get("id", ""))
    existing_ledger_rows = ledger_rows_for_transaction(original_uid, include_void=False) if original_uid else []
    old_had_credit_ledger = any(str(row.get("movement_kind") or "") == "credit_liability_increase" for row in existing_ledger_rows)
    has_new_payment_context = transaction_has_payment_snapshots(original) or bool(existing_ledger_rows) or bool(tx_input.payment_method_id or tx_input.account_id)
    data["transaction_uid"] = original_uid

    if not has_new_payment_context:
        update_transaction(original.get("id", ""), original.get("type", ""), data)
        return {"ok": True, "message": "Legacy transaction updated."}

    route_data = dict(original)
    route_data.update(data)
    if tx_input.payment_method_id:
        # The edit page's visible selector is the source of truth.  Do not keep
        # the old payment_channel_method_id_snapshot as a hidden submitted value:
        # otherwise changing PayPal balance -> PayPal via Credit Card can look
        # selected in the browser but still rebuild through the old route.
        route_data["payment_method_id"] = tx_input.payment_method_id
        route_data["payment_channel_method_id"] = tx_input.payment_method_id
    else:
        route_data["payment_method_id"] = original.get("payment_method_id", "")
        route_data["payment_channel_method_id"] = original.get("payment_channel_method_id_snapshot", "")
    route_data["account_id"] = selected_account_id or _effective_account_id_for_edit(original, route_data, tx_input)

    payment_changed = (
        tx_input.force_payment_rebuild
        or _payment_affecting_changed(original, route_data)
        or _submitted_payment_context_changed(original, route_data, tx_input)
    )
    if not payment_changed:
        update_transaction(original.get("id", ""), original.get("type", ""), data)
        return {"ok": True, "message": "Transaction metadata updated; ledger route unchanged."}

    settled_credit = _looks_like_settled_credit(original, existing_ledger_rows)
    if settled_credit and not tx_input.confirm_settled_edit:
        return {
            "ok": False,
            "requires_confirmation": True,
            "error": "This looks like a settled/due credit transaction. Confirm the settled edit to create adjustment ledger rows instead of silently rewriting history.",
        }

    resolution = resolve_payment(
        str(original.get("type") or "").casefold(),
        _to_float(route_data.get("amount")),
        route_data.get("date") or date.today().isoformat(),
        account_id=_account_hint_for_resolution(route_data) or None,
        payment_method_id=route_data.get("payment_method_id") or None,
        category=route_data.get("category"),
        sub_category=route_data.get("sub_category"),
        description=str(route_data.get("description") or ""),
        existing_row=route_data,
    )
    if not resolution.ok:
        return {"ok": False, "error": "; ".join(resolution.errors) or "Payment route could not be rebuilt.", "warnings": resolution.warnings}

    reason = f"Payment route rebuilt for {original_uid}."
    if settled_credit:
        ledger_report = append_adjustment_rows_for_transaction(original_uid, reason=reason)
    else:
        ledger_report = void_ledger_for_transaction(original_uid, reason=reason)

    new_ledger_rows = rows_from_payment_resolution(
        resolution,
        transaction_uid=original_uid,
        transaction_type=str(original.get("type") or "").casefold(),
        transaction_id=str(original.get("id") or ""),
        source_kind="transaction_edit",
        source_id=str(original.get("id") or ""),
    )
    ledger_ids = append_ledger_movements(new_ledger_rows) if new_ledger_rows else []
    data.update(_transaction_metadata_from_resolution(route_data, resolution))
    data["transaction_uid"] = original_uid
    data["ledger_group_id"] = resolution.ledger_group_id
    data["ledger_status"] = "adjusted_rebuilt" if settled_credit else "rebuilt"
    data["description"] = _with_audit_note(str(data.get("description") or ""), reason)
    update_transaction(original.get("id", ""), original.get("type", ""), data)
    _sync_credit_settlements_if_needed(new_ledger_rows, force=old_had_credit_ledger)
    return {"ok": True, "message": "Payment route rebuilt.", "ledger_report": ledger_report, "ledger_ids": ledger_ids, "warnings": resolution.warnings}


def delete_existing_transaction(row_index: int, confirm_settled_edit: bool = False) -> dict:
    df = load_transactions()
    row = df.loc[row_index]
    original = _plain_row(row)
    uid = original.get("transaction_uid") or make_transaction_uid(original.get("type", ""), original.get("id", ""))
    existing_ledger_rows = ledger_rows_for_transaction(uid, include_void=False) if uid else []
    has_ledger_context = transaction_has_payment_snapshots(original) or bool(existing_ledger_rows)

    old_had_credit_ledger = any(str(row.get("movement_kind") or "") == "credit_liability_increase" for row in existing_ledger_rows)
    if has_ledger_context:
        settled_credit = _looks_like_settled_credit(original, existing_ledger_rows)
        if settled_credit and not confirm_settled_edit:
            return {
                "ok": False,
                "requires_confirmation": True,
                "error": "This looks like a settled/due credit transaction. Confirm deletion to create adjustment ledger rows before removing the CSV row.",
            }
        reason = f"Transaction {uid} deleted."
        if settled_credit:
            append_adjustment_rows_for_transaction(uid, reason=reason)
        else:
            void_ledger_for_transaction(uid, reason=reason)

    deleted = delete_transaction(original.get("id", ""), original.get("type", ""))
    if old_had_credit_ledger:
        _sync_credit_settlements_if_needed([], force=True)
    return {"ok": bool(deleted), "message": "Transaction deleted." if deleted else "Transaction not found."}


def _transaction_metadata_from_resolution(tx: Mapping[str, Any], resolution) -> dict[str, Any]:
    wrapper_id = ""
    wrapper_name = ""
    try:
        created = dict(resolution.created_from_resolution or {})
        wrapper_id = str(created.get("wrapper_payment_method_id") or "")
        wrapper_name = str(created.get("wrapper_payment_method_name_snapshot") or "")
    except Exception:
        pass

    account_id = resolution.account_id or resolution.liability_account_id or resolution.funding_account_id or tx.get("account_id", "")
    account_name = resolution.account_name_snapshot or _account_label(account_id)
    funding_id = resolution.funding_account_id or ""
    settlement_id = resolution.settlement_account_id or ""
    liability_id = resolution.liability_account_id or ""
    method_id = resolution.payment_method_id or tx.get("payment_method_id", "")
    method_name = resolution.payment_method_name_snapshot or method_id
    channel_id = wrapper_id or tx.get("payment_channel_method_id") or method_id
    channel_name = wrapper_name or method_name

    legacy_account = str(tx.get("account") or "")

    # Delegated wallet/card methods need a CSV-compatible account marker that
    # represents the real money route, not the visible checkout wallet.  If the
    # form selection remains account=PayPal while the method is PayPal via Credit
    # Card, keeping "PayPal" here makes the PayPal wallet balance drop by the
    # purchase amount.  Store the legacy credit-route alias instead so PayPal can
    # show a zero-balance trace row while the real payment waits for the card
    # settlement.
    route_channel_id = (channel_id or method_id or "").strip()
    if route_channel_id == "paypal_via_credit_card":
        legacy_account = PAYPAL_CREDIT_ACCOUNT_VALUE
    elif route_channel_id == "paypal_via_main_bank":
        legacy_account = "paypal card"
    elif not legacy_account and account_id and account_id != MAIN_ACCOUNT_KEY:
        legacy_account = account_id

    return {
        "account": legacy_account,
        "account_id": account_id,
        "account_key_snapshot": account_id,
        "account_name_snapshot": account_name,
        "account_due_day_snapshot": str(resolution.due_day_snapshot or ""),
        "payment_method": method_name or str(tx.get("payment_method") or ""),
        "payment_method_id": method_id,
        "payment_method_name_snapshot": method_name,
        "payment_channel_method_id_snapshot": channel_id,
        "payment_channel_name_snapshot": channel_name,
        "funding_account_id_snapshot": funding_id,
        "funding_account_name_snapshot": _account_label(funding_id),
        "settlement_account_id_snapshot": settlement_id,
        "settlement_account_name_snapshot": _account_label(settlement_id),
        "liability_account_id_snapshot": liability_id,
        "liability_account_name_snapshot": _account_label(liability_id),
        "settlement_mode_snapshot": resolution.settlement_mode,
        "payment_due_date_snapshot": resolution.due_date,
        "payment_due_day_snapshot": str(resolution.due_day_snapshot or ""),
        "payment_statement_period_snapshot": resolution.statement_period,
        "payment_resolution_json": resolution_json_dumps(resolution),
        "ledger_group_id": resolution.ledger_group_id,
        "ledger_status": "posted" if resolution.movements else "resolved_no_movement",
    }


def _account_hint_for_resolution(tx: Mapping[str, Any]) -> str:
    return _first_nonblank(tx.get("account_id"), tx.get("account_key_snapshot"), tx.get("account"))


def _effective_account_id_for_edit(original: Mapping[str, Any], route_data: Mapping[str, Any], tx_input: TransactionInput) -> str:
    old_account = str(original.get("account") or "")
    new_account = str(route_data.get("account") or "")
    if new_account != old_account:
        return normalize_account_key(new_account) if new_account else MAIN_ACCOUNT_KEY
    return _first_nonblank(tx_input.account_id, original.get("account_id"), original.get("account_key_snapshot"), normalize_account_key(new_account))


def _submitted_payment_context_changed(original: Mapping[str, Any], route_data: Mapping[str, Any], tx_input: TransactionInput) -> bool:
    """Return True when the edit form explicitly changed the visible route.

    Some existing rows store both the real method and a visible wrapper/channel
    snapshot.  For example, a PayPal payment can show a PayPal wrapper while the
    old row still carries a previous immediate PayPal-balance route.  Comparing
    only the normalized legacy context may miss that UI-level intent, so the
    posted stable ids are checked directly.
    """
    submitted_method = str(tx_input.payment_method_id or "").strip()
    if submitted_method:
        original_primary_method = str(original.get("payment_method_id") or "").strip()
        original_channel_method = str(original.get("payment_channel_method_id_snapshot") or "").strip()
        # The visible selector must win over the old primary route.  Older rows
        # could have payment_method_id=paypal_balance while the visible/channel
        # snapshot already said paypal_via_credit_card; accepting the channel as
        # "unchanged" kept the PayPal balance route alive and left settlements
        # wrong.  Rebuild whenever the submitted visible method differs from the
        # primary stored method.
        if submitted_method != original_primary_method:
            return True
        if original_channel_method and original_channel_method != submitted_method:
            return True

    submitted_account = str(tx_input.account_id or "").strip()
    if submitted_account:
        original_accounts = {
            str(original.get("account_id") or "").strip(),
            str(original.get("account_key_snapshot") or "").strip(),
            normalize_account_key(str(original.get("account") or "")),
        }
        if submitted_account not in original_accounts:
            return True

    return False


def _payment_affecting_changed(original: Mapping[str, Any], route_data: Mapping[str, Any]) -> bool:
    old_context = transaction_row_to_payment_context(original)
    new_context = transaction_row_to_payment_context(route_data)
    for field in PAYMENT_AFFECTING_FIELDS:
        old_value = old_context.get(field, original.get(field, ""))
        new_value = new_context.get(field, route_data.get(field, ""))
        if field == "amount":
            if round(_to_float(old_value), 2) != round(_to_float(new_value), 2):
                return True
        else:
            if _normalize_compare(old_value) != _normalize_compare(new_value):
                return True
    return False


def _looks_like_settled_credit(row: Mapping[str, Any], ledger_rows: list[dict[str, Any]]) -> bool:
    due = _parse_date(row.get("payment_due_date_snapshot"))
    if due and due <= date.today():
        return True
    settlement_mode = str(row.get("settlement_mode_snapshot") or "").casefold()
    has_due_snapshot = bool(str(row.get("payment_due_date_snapshot") or "").strip())
    if settlement_mode == "delayed" and has_due_snapshot and due is None:
        return True
    for ledger in ledger_rows:
        status = str(ledger.get("status") or "").casefold()
        movement = str(ledger.get("movement_kind") or "").casefold()
        direction = str(ledger.get("direction") or "").casefold()
        if status in SETTLED_LEDGER_STATUSES:
            return True
        if "settlement" in movement or direction == "liability_decrease":
            return True
    return False


def _route_explanation_from_row(row: Mapping[str, Any], ledger_rows: list[dict[str, Any]]) -> str:
    text = str(row.get("payment_resolution_json") or "").strip()
    for candidate in [text, *[str(item.get("created_from_resolution_json") or "") for item in ledger_rows]]:
        if not candidate:
            continue
        try:
            payload = json.loads(candidate)
        except (TypeError, json.JSONDecodeError):
            continue
        explanation = str(payload.get("display_explanation") or "").strip()
        if explanation:
            return explanation
    return ""


def _plain_row(row) -> dict[str, Any]:
    if hasattr(row, "to_dict"):
        raw = row.to_dict()
    else:
        raw = dict(row)
    cleaned: dict[str, Any] = {}
    for key, value in raw.items():
        if isinstance(value, pd.Timestamp):
            cleaned[key] = value.strftime("%Y-%m-%d") if not pd.isna(value) else ""
        elif pd.isna(value) if not isinstance(value, (list, dict, tuple, set)) else False:
            cleaned[key] = ""
        else:
            cleaned[key] = value
    return cleaned


def _date_str(value: Any) -> str:
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    text = str(value or "")
    return text[:10] if len(text) >= 10 else text


def _clean_display(value: Any) -> str:
    text = str(value or "")
    return "" if text.casefold() in {"nan", "nat", "none", "null"} else text


def _with_audit_note(description: str, note: str) -> str:
    marker = f"[{note}]"
    if marker in description:
        return description
    return f"{description} {marker}".strip() if description else marker


def _account_label(account_id: Any) -> str:
    text = str(account_id or "").strip()
    if not text:
        return ""
    try:
        return account_label_for_key(text)
    except Exception:
        return text


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None


def _first_nonblank(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text and text.casefold() not in {"nan", "nat", "none", "null"}:
            return text
    return ""


def _normalize_compare(value: Any) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _to_float(value: Any) -> float:
    try:
        return float(str(value or "0").replace(",", "."))
    except (TypeError, ValueError):
        return 0.0
