from datetime import date, timedelta

import pandas as pd

from money_manager.config import (
    CREDIT_ACCOUNT_KEYWORDS,
    CREDIT_CARD_DUE_DAY,
    MAIN_ACCOUNT_KEY,
    PAYPAL_ACCOUNT_KEY,
    PAYPAL_CREDIT_ACCOUNT_VALUE,
    TRANSACTION_TYPES,
    account_label_for_key,
    auxiliary_account_keys,
    normalize_account_key,
)
from money_manager.domain.transaction import TransactionInput
from money_manager.services.currency_service import append_conversion_note, convert_amount_to_eur
from money_manager.repositories.pending import append_pending
from money_manager.repositories.transactions import (
    append_transaction,
    delete_transaction,
    load_all,
    update_transaction,
)

BALANCE_METHOD_BALANCE = "balance"
BALANCE_METHOD_CREDIT = "credit"
BALANCE_METHOD_ANOTHER_CARD = "another_card"
BALANCE_INSUFFICIENT_STOP = "stop"
BALANCE_INSUFFICIENT_ANOTHER_CARD = "use_another_card_for_remaining"
BALANCE_INSUFFICIENT_CREDIT = "use_credit_for_remaining"

# Backwards-compatible names used by templates/forms.
PAYPAL_METHOD_BALANCE = BALANCE_METHOD_BALANCE
PAYPAL_METHOD_CREDIT = BALANCE_METHOD_CREDIT
PAYPAL_METHOD_ANOTHER_CARD = BALANCE_METHOD_ANOTHER_CARD
PAYPAL_INSUFFICIENT_STOP = BALANCE_INSUFFICIENT_STOP
PAYPAL_INSUFFICIENT_ANOTHER_CARD = BALANCE_INSUFFICIENT_ANOTHER_CARD
PAYPAL_INSUFFICIENT_CREDIT = BALANCE_INSUFFICIENT_CREDIT


def next_credit_due(payment_date=None, due_day: int = CREDIT_CARD_DUE_DAY) -> date:
    payment_date = payment_date or date.today()

    if payment_date.month == 12:
        return date(payment_date.year + 1, 1, due_day)

    return date(payment_date.year, payment_date.month + 1, due_day)


def save_new_transaction(tx_input: TransactionInput) -> dict:
    """Save a new transaction and return a small UI-friendly result.

    PayPal and every Other/custom balance account share the same logic:
    - balance method spends from that tracked auxiliary balance;
    - credit method creates a pending credit-card/PayPal-credit row;
    - another_card method records a main-bank/card outflow;
    - when the auxiliary balance is too small, the remaining amount can be sent
      either to main bank/card or to pending credit.
    """
    tx = _transaction_payload_in_eur(tx_input)
    return save_transaction_payload(
        tx,
        payment_method=tx_input.paypal_payment_method,
        insufficient_action=tx_input.paypal_insufficient_action,
        due_date=_due_date_from_input(tx_input),
    )


def save_transaction_payload(
    tx: dict,
    payment_method: str = BALANCE_METHOD_BALANCE,
    insufficient_action: str = BALANCE_INSUFFICIENT_STOP,
    due_date: date | None = None,
) -> dict:
    """Save an already-normalized transaction dict using the shared account router.

    This is intentionally reusable by debts, payables, projects, receivables and
    any future form that records an expense. It avoids the old bug where only the
    normal Add Transaction page understood PayPal/credit split payments.
    """
    tx = dict(tx)
    account_raw = str(tx.get("account", "") or "").strip()
    account_key = normalize_account_key(account_raw)
    tx_type = str(tx.get("type", "") or "").casefold()
    due_date = due_date or _due_date_from_payload(tx)

    if tx_type == "expense" and account_key in auxiliary_account_keys():
        return _save_balance_account_expense(
            tx,
            account_key=account_key,
            method=(payment_method or BALANCE_METHOD_BALANCE),
            insufficient_action=(insufficient_action or BALANCE_INSUFFICIENT_STOP),
            due=due_date,
        )

    if tx_type == "expense" and account_raw.casefold() in CREDIT_ACCOUNT_KEYWORDS:
        tx["account"] = "credit"
        pending_id = append_pending(tx, due_date)
        return {"ok": True, "message": "Credit-card payment added to pending.", "transaction_ids": [], "pending_ids": [pending_id] if pending_id is not None else []}

    tx_id = append_transaction(tx)
    return {"ok": True, "message": "Transaction saved.", "transaction_ids": [tx_id], "pending_ids": []}


def account_balance(account_key: str) -> float:
    """Current balance of any auxiliary account."""
    from money_manager.services.account_service import account_balance_rows

    key = normalize_account_key(account_key)
    rows = account_balance_rows(load_all())
    for row in rows:
        if row.get("key") == key:
            return float(row.get("balance", 0.0) or 0.0)
    return 0.0


def account_balances_for_preview() -> dict:
    from money_manager.services.account_service import account_balance_rows

    return {row.get("key"): float(row.get("balance", 0.0) or 0.0) for row in account_balance_rows(load_all())}


def main_net_for_preview() -> float:
    from money_manager.services.account_service import main_account_transactions

    df = main_account_transactions(load_all())
    if df.empty:
        return 0.0
    return float(df.get("signed_amount", 0).sum())


def paypal_balance() -> float:
    """Current balance of the PayPal auxiliary account."""
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
        method=tx_input.paypal_payment_method or BALANCE_METHOD_BALANCE,
        insufficient_action=tx_input.paypal_insufficient_action or BALANCE_INSUFFICIENT_STOP,
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
    return next_credit_due(payment_date)


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


def _due_date_from_payload(tx: dict) -> date:
    try:
        payment_date = date.fromisoformat(str(tx.get("date", "") or ""))
    except (TypeError, ValueError):
        payment_date = date.today()
    return next_credit_due(payment_date)


def load_transactions() -> pd.DataFrame:
    return load_all()


def prepare_transactions_for_display(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if df.empty:
        df["date_str"] = []
        df["amount_str"] = []
        df["row_index"] = []
        return df

    df["date_str"] = df["date"].dt.strftime("%Y-%m-%d")
    df["amount_str"] = df["amount"].map(lambda amount: f"{amount:.2f}")
    df["row_index"] = df.index
    df["delay_date_default"] = (date.today() + timedelta(days=1)).isoformat()
    return df


def transaction_detail_context(row_index: int) -> tuple[dict, list[str]]:
    from money_manager.config import categories_for

    df = load_all()

    try:
        row = df.loc[row_index]
    except KeyError as exc:
        raise LookupError(f"Transaction {row_index} not found") from exc

    date_str = row["date"].strftime("%Y-%m-%d") if hasattr(row["date"], "strftime") else str(row.get("date", ""))

    def clean(value):
        return "" if str(value) == "nan" else value

    tx = {
        "id": int(row_index),
        "csv_id": int(row["id"]),
        "type": row["type"],
        "date": date_str,
        "category": clean(row.get("category", "")),
        "sub_category": clean(row.get("sub_category", "")),
        "amount": f"{row['amount']:.2f}",
        "original_amount": clean(row.get("original_amount", "")),
        "original_currency": clean(row.get("original_currency", "")),
        "exchange_rate_to_eur": clean(row.get("exchange_rate_to_eur", "")),
        "exchange_correction_to_eur": clean(row.get("exchange_correction_to_eur", "")),
        "exchange_effective_rate_to_eur": clean(row.get("exchange_effective_rate_to_eur", "")),
        "account": clean(row.get("account", "")),
        "account_key": clean(row.get("account_key", normalize_account_key(row.get("account", "")))),
        "account_label": clean(row.get("account_label", "")),
        "description": clean(row.get("description", "")),
        "delay_date_default": (date.today() + timedelta(days=1)).isoformat(),
    }

    return tx, categories_for(tx["type"])


def delay_existing_transaction(row_index: int, new_date: str) -> None:
    if not new_date:
        return

    df = load_all()
    row = df.loc[row_index]

    update_transaction(
        int(row["id"]),
        row["type"],
        {"date": new_date},
    )


def update_existing_transaction(row_index: int, form) -> None:
    df = load_all()
    row = df.loc[row_index]
    tx_input = TransactionInput.from_form({**form, "type": row["type"]})

    data = {
        "date": tx_input.date,
        "category": tx_input.category,
        "sub_category": tx_input.sub_category,
        "amount": tx_input.amount,
        "account": tx_input.account,
        "description": tx_input.description,
    }

    # The transaction detail screen edits the already-saved EUR value.  The add
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

    update_transaction(int(row["id"]), row["type"], data)


def delete_existing_transaction(row_index: int) -> None:
    df = load_all()
    row = df.loc[row_index]
    delete_transaction(int(row["id"]), row["type"])
