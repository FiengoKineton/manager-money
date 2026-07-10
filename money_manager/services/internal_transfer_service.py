from __future__ import annotations

import json
import uuid
from datetime import date
from typing import Any, Mapping

import pandas as pd

from money_manager.config import MAIN_ACCOUNT_KEY, MAIN_ACCOUNT_LABEL
from money_manager.domain.payment import LedgerMovementDraft
from money_manager.repositories.internal_transfers import (
    append_transfer,
    delete_transfer,
    find_transfer,
    load_all,
    update_transfer,
)
from money_manager.repositories.transactions import append_transaction, update_transaction
from money_manager.services.account_config_service import (
    account_by_key,
    account_label_for_key,
    active_accounts,
    configured_account_key,
    normalize_account_key,
)
from money_manager.services.account_ledger_service import append_ledger_movements, void_ledger_group
from money_manager.services.payment_method_service import payment_method_by_id, payment_method_options_for_forms
from money_manager.services.payment_routing_service import resolve_payment
from money_manager.services.account_ledger_service import rows_from_payment_resolution

TRANSFER_KIND_OPTIONS = {
    "normal_transfer",
    "prepaid_topup",
    "wallet_topup",
    "cash_deposit",
    "cash_withdrawal",
    "account_closure_balance_move",
    "credit_settlement",
    "adjustment",
}


def account_choices(include_closed: bool = False, allow_containers: bool = False, include_credit: bool = False) -> list[dict[str, Any]]:
    """Choices allowed for internal transfers.

    Internal transfer now means a real balance move from one account bucket to
    another. Payment methods are deliberately not listed here.
    """
    rows: list[dict[str, Any]] = []
    for account in active_accounts(include_main=True):
        key = str(account.get("key") or account.get("id") or "")
        if not key:
            continue
        if account.get("is_closed") and not include_closed:
            continue
        if account.get("is_container") and not allow_containers:
            continue
        if _is_credit_liability(account) and not include_credit:
            continue
        rows.append({
            "key": key,
            "id": key,
            "value": key,
            "label": account.get("label") or account.get("name") or key,
            "is_container": bool(account.get("is_container")),
            "is_closed": bool(account.get("is_closed")),
            "main_net_policy": account.get("main_net_policy", ""),
            "account_kind": account.get("account_kind") or account.get("type") or "",
        })
    if MAIN_ACCOUNT_KEY not in {row["key"] for row in rows}:
        rows.insert(0, {"key": MAIN_ACCOUNT_KEY, "id": MAIN_ACCOUNT_KEY, "value": MAIN_ACCOUNT_KEY, "label": MAIN_ACCOUNT_LABEL})
    return rows


def _parse_amount(value: Any) -> float:
    try:
        return round(float(str(value or "0").replace(",", ".")), 2)
    except (TypeError, ValueError):
        return 0.0


def _parse_date(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return date.today().isoformat()
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        pass
    for sep in ("/", "-"):
        parts = text.split(sep)
        if len(parts) == 3 and len(parts[2]) == 4:
            day, month, year = parts
            try:
                return date(int(year), int(month), int(day)).isoformat()
            except ValueError:
                break
    return text


def _account_key_from_value(value: Any, *, strict: bool = False) -> str:
    resolved = configured_account_key(str(value or ""))
    if resolved:
        return resolved
    return "" if strict else normalize_account_key(str(value or ""))


def _account_for_transfer(value: Any, *, allow_closed: bool = False, allow_container: bool = False, include_credit: bool = False) -> tuple[dict[str, Any] | None, str]:
    key = _account_key_from_value(value, strict=True)
    if not key:
        return None, "Account does not exist or is no longer active. Refresh the page and choose it again."
    account = account_by_key(key, include_archived=True)
    if not account:
        return None, "Account does not exist."
    if account.get("is_closed") and not allow_closed:
        return None, f"{account_label_for_key(key)} is closed and cannot be used for a new transfer."
    if not account.get("is_active", True) and not allow_closed:
        return None, f"{account_label_for_key(key)} is archived and cannot be used for a new transfer."
    if account.get("is_container") and not allow_container:
        return None, f"{account_label_for_key(key)} is a container. Choose a real account inside it."
    if _is_credit_liability(account) and not include_credit:
        return None, f"{account_label_for_key(key)} is a credit liability account. Use credit settlement instead."
    return account, ""


def _is_credit_liability(account: Mapping[str, Any]) -> bool:
    kind = str(account.get("account_kind") or account.get("type") or "")
    return kind == "credit_card_liability" or bool(account.get("is_liability"))


def _legacy_saved_account_for_key(key: str) -> str:
    return "" if key == MAIN_ACCOUNT_KEY else account_label_for_key(key)


def _balance_snapshot_for_form() -> dict[str, float]:
    """Calculate every available account balance using the existing dashboard math.

    Ledger rows are now written for new transfers, but old CSV-era account pages
    still derive many balances from transaction/account history. Reusing the
    existing snapshot keeps the transfer form compatible during the migration.
    """
    from money_manager.services.account_service import account_balance_rows, main_account_transactions
    from money_manager.services.transaction_service import load_transactions

    df = load_transactions()
    main_rows = main_account_transactions(df)
    main_balance = 0.0
    if not main_rows.empty and "signed_amount" in main_rows.columns:
        main_balance = float(main_rows["signed_amount"].sum())

    rows_by_key = {row.get("key"): row for row in account_balance_rows(df)}
    balances = {MAIN_ACCOUNT_KEY: round(main_balance, 2)}
    for choice in account_choices(include_credit=True):
        key = choice.get("key")
        if key == MAIN_ACCOUNT_KEY:
            continue
        row = rows_by_key.get(key, {})
        balances[key] = round(float(row.get("balance", 0.0) or 0.0), 2)
    return balances


def _available_balance_for_key(account_key: str) -> float:
    key = _account_key_from_value(account_key)
    return float(_balance_snapshot_for_form().get(key, 0.0) or 0.0)


def account_balances_for_form() -> dict[str, float]:
    return _balance_snapshot_for_form()


def validate_transfer(form: Mapping[str, Any], check_balance: bool = True, *, allow_closed: bool = False, allow_container: bool = False, include_credit: bool = False) -> tuple[dict[str, Any] | None, str]:
    from_account_raw = form.get("from_account_id") or form.get("from_account", "")
    to_account_raw = form.get("to_account_id") or form.get("to_account", "")
    from_account, error = _account_for_transfer(from_account_raw, allow_closed=allow_closed, allow_container=allow_container, include_credit=include_credit)
    if error:
        return None, error
    to_account, error = _account_for_transfer(to_account_raw, allow_closed=allow_closed, allow_container=allow_container, include_credit=include_credit)
    if error:
        return None, error

    from_key = str(from_account.get("key") or from_account.get("id") or MAIN_ACCOUNT_KEY)
    to_key = str(to_account.get("key") or to_account.get("id") or MAIN_ACCOUNT_KEY)
    amount = _parse_amount(form.get("amount", "0"))

    if str(form.get("move_all", "")).strip():
        amount = _available_balance_for_key(from_key)

    if amount <= 0:
        return None, "Amount must be greater than zero."
    if from_key == to_key:
        return None, "Choose two different accounts for the transfer."

    if check_balance:
        available = _available_balance_for_key(from_key)
        if amount > available + 0.005:
            return None, (
                f"Not enough money in {account_label_for_key(from_key)}: "
                f"available € {available:.2f}, trying to move € {amount:.2f}."
            )

    fee_amount = _parse_amount(form.get("fee_amount", "0"))
    method_id = str(form.get("fee_payment_method_id") or "").strip()
    method = payment_method_by_id(method_id, include_archived=False) if method_id else None
    transfer_kind = str(form.get("transfer_kind") or "normal_transfer").strip() or "normal_transfer"
    if transfer_kind not in TRANSFER_KIND_OPTIONS:
        transfer_kind = "normal_transfer"

    return {
        "date": _parse_date(str(form.get("date", ""))),
        "from_account": _legacy_saved_account_for_key(from_key),
        "to_account": _legacy_saved_account_for_key(to_key),
        "from_account_id": from_key,
        "from_account_name_snapshot": account_label_for_key(from_key),
        "to_account_id": to_key,
        "to_account_name_snapshot": account_label_for_key(to_key),
        "amount": amount,
        "fee_amount": fee_amount,
        "fee_payment_method_id": method_id,
        "fee_payment_method_name_snapshot": method.get("name", "") if method else "",
        "transfer_kind": transfer_kind,
        "status": "posted",
        "description": str(form.get("description", "") or "").strip(),
    }, ""


def create_transfer(form: Mapping[str, Any]) -> dict[str, Any]:
    data, error = validate_transfer(form)
    if error:
        return {"ok": False, "error": error}
    transfer_uid = f"transfer:{uuid.uuid4().hex}"
    ledger_group_id = f"tr_{uuid.uuid4().hex}"
    data.update({"transfer_uid": transfer_uid, "ledger_group_id": ledger_group_id})
    transfer_id = append_transfer(data)
    ledger_ids = _append_transfer_ledger_rows(data, transfer_id=transfer_id)
    fee_report = _append_transfer_fee(data, transfer_id=transfer_id)
    metadata = {"fee": fee_report, "ledger_ids": ledger_ids}
    update_transfer(transfer_id, {"metadata_json": json.dumps(metadata, ensure_ascii=False)})
    message = "Internal transfer saved and ledger movements posted."
    if fee_report.get("created"):
        message += " Transfer fee was saved separately."
    elif data.get("fee_amount", 0) > 0:
        message += " Transfer fee was ignored because no valid fee route was configured."
    return {"ok": True, "message": message, "transfer_id": transfer_id, "ledger_ids": ledger_ids, "fee": fee_report}


def _append_transfer_ledger_rows(data: Mapping[str, Any], *, transfer_id: int | str) -> list[str]:
    amount = _parse_amount(data.get("amount"))
    if amount <= 0:
        return []
    ledger_group_id = str(data.get("ledger_group_id") or f"tr_{uuid.uuid4().hex}")
    from_key = str(data.get("from_account_id") or _account_key_from_value(data.get("from_account")))
    to_key = str(data.get("to_account_id") or _account_key_from_value(data.get("to_account")))
    transfer_uid = str(data.get("transfer_uid") or f"transfer:{transfer_id}")
    created_json = json.dumps({
        "transfer_uid": transfer_uid,
        "transfer_kind": data.get("transfer_kind") or "normal_transfer",
        "from_account_id": from_key,
        "to_account_id": to_key,
    }, ensure_ascii=False)
    base = {
        "ledger_group_id": ledger_group_id,
        "transaction_uid": transfer_uid,
        "transaction_type": "internal_transfer",
        "transaction_id": str(transfer_id),
        "source_kind": "internal_transfer",
        "source_id": str(transfer_id),
        "date": data.get("date") or date.today().isoformat(),
        "effective_date": data.get("date") or date.today().isoformat(),
        "currency": "EUR",
        "status": data.get("status") or "posted",
        "created_from_resolution_json": created_json,
        "notes": data.get("description", ""),
    }
    movements = [
        {
            **base,
            "account_id": from_key,
            "account_name_snapshot": data.get("from_account_name_snapshot") or account_label_for_key(from_key),
            "counterparty_account_id": to_key,
            "counterparty_account_name_snapshot": data.get("to_account_name_snapshot") or account_label_for_key(to_key),
            "movement_kind": data.get("transfer_kind") or "normal_transfer",
            "direction": "out",
            "amount": amount,
            "signed_amount": -amount,
        },
        {
            **base,
            "account_id": to_key,
            "account_name_snapshot": data.get("to_account_name_snapshot") or account_label_for_key(to_key),
            "counterparty_account_id": from_key,
            "counterparty_account_name_snapshot": data.get("from_account_name_snapshot") or account_label_for_key(from_key),
            "movement_kind": data.get("transfer_kind") or "normal_transfer",
            "direction": "in",
            "amount": amount,
            "signed_amount": amount,
        },
    ]
    return append_ledger_movements(movements)


def _append_transfer_fee(data: Mapping[str, Any], *, transfer_id: int | str) -> dict[str, Any]:
    fee_amount = _parse_amount(data.get("fee_amount"))
    if fee_amount <= 0:
        return {"created": False, "reason": "no_fee"}
    method_id = str(data.get("fee_payment_method_id") or "").strip()
    if not method_id:
        return {"created": False, "reason": "missing_fee_payment_method"}
    method = payment_method_by_id(method_id, include_archived=False)
    if not method:
        return {"created": False, "reason": "unknown_fee_payment_method"}

    tx = {
        "type": "expense",
        "date": data.get("date") or date.today().isoformat(),
        "category": "Bank fees",
        "sub_category": "Internal transfer fee",
        "amount": fee_amount,
        "payment_method_id": method_id,
        "payment_method": method_id,
        "description": f"Fee for internal transfer #{transfer_id}: {data.get('from_account_name_snapshot')} → {data.get('to_account_name_snapshot')}.",
    }
    resolution = resolve_payment(
        "expense",
        fee_amount,
        tx["date"],
        payment_method_id=method_id,
        category=tx["category"],
        sub_category=tx["sub_category"],
        description=tx["description"],
        existing_row=tx,
    )
    if resolution.ok:
        tx.update({
            "account_id": resolution.account_id,
            "account_name_snapshot": resolution.account_name_snapshot,
            "payment_method_name_snapshot": resolution.payment_method_name_snapshot,
            "funding_account_id_snapshot": resolution.funding_account_id,
            "funding_account_name_snapshot": account_label_for_key(resolution.funding_account_id),
            "settlement_account_id_snapshot": resolution.settlement_account_id,
            "settlement_account_name_snapshot": account_label_for_key(resolution.settlement_account_id),
            "liability_account_id_snapshot": resolution.liability_account_id,
            "liability_account_name_snapshot": account_label_for_key(resolution.liability_account_id),
            "settlement_mode_snapshot": resolution.settlement_mode,
            "payment_due_date_snapshot": resolution.due_date,
            "payment_due_day_snapshot": resolution.due_day_snapshot or "",
            "payment_statement_period_snapshot": resolution.statement_period,
            "payment_resolution_json": json.dumps(resolution.to_dict(), ensure_ascii=False),
            "ledger_group_id": resolution.ledger_group_id,
            "ledger_status": "posted",
        })
    tx_id = append_transaction(tx)
    if resolution.ok:
        uid = f"expense:{tx_id}"
        ledger_rows = rows_from_payment_resolution(
            resolution,
            transaction_uid=uid,
            transaction_type="expense",
            transaction_id=str(tx_id),
            source_kind="internal_transfer_fee",
            source_id=str(transfer_id),
        )
        append_ledger_movements(ledger_rows)
        update_transaction(tx_id, "expense", {"transaction_uid": uid, "ledger_group_id": resolution.ledger_group_id, "ledger_status": "posted"})
    return {"created": True, "transaction_id": tx_id, "ledger_group_id": resolution.ledger_group_id if resolution.ok else ""}


def update_transfer_from_form(form: Mapping[str, Any]) -> dict[str, Any]:
    data, error = validate_transfer(form, check_balance=False)
    if error:
        return {"ok": False, "error": error}
    try:
        transfer_id = int(form.get("id", "0"))
    except ValueError:
        return {"ok": False, "error": "Missing transfer id."}
    existing = find_transfer(transfer_id)
    if not existing:
        return {"ok": False, "error": "Transfer not found."}
    old_group = str(existing.get("ledger_group_id") or "")
    if old_group:
        void_ledger_group(old_group, reason=f"Internal transfer #{transfer_id} edited")
    data.update({
        "transfer_uid": existing.get("transfer_uid") or f"transfer:{uuid.uuid4().hex}",
        "ledger_group_id": f"tr_{uuid.uuid4().hex}",
        "status": "posted",
    })
    previous_metadata = _safe_json_object(existing.get("metadata_json"))
    update_transfer(transfer_id, data)
    ledger_ids = _append_transfer_ledger_rows(data, transfer_id=transfer_id)
    fee_report = {"created": False, "reason": "existing_fee_preserved"}
    if data.get("fee_amount", 0) > 0 and not previous_metadata.get("fee", {}).get("transaction_id"):
        fee_report = _append_transfer_fee(data, transfer_id=transfer_id)
    metadata = {"fee": previous_metadata.get("fee") or fee_report, "ledger_ids": ledger_ids, "edited_from_ledger_group_id": old_group}
    update_transfer(transfer_id, {"metadata_json": json.dumps(metadata, ensure_ascii=False)})
    return {"ok": True, "message": "Internal transfer updated and ledger movements rebuilt."}


def delete_transfer_from_form(form: Mapping[str, Any]) -> dict[str, Any]:
    try:
        transfer_id = int(form.get("id", "0"))
    except ValueError:
        return {"ok": False, "error": "Missing transfer id."}
    existing = find_transfer(transfer_id)
    if existing and existing.get("ledger_group_id"):
        void_ledger_group(str(existing.get("ledger_group_id")), reason=f"Internal transfer #{transfer_id} deleted")
    delete_transfer(transfer_id)
    return {"ok": True, "message": "Internal transfer deleted and ledger movements voided."}


def _safe_json_object(value: Any) -> dict[str, Any]:
    text = str(value or "").strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _clean_saved_account(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in {"nan", "none", "null"} else text


def _key_for_transfer_row(row: Mapping[str, Any], side: str) -> str:
    id_field = f"{side}_account_id"
    legacy_field = f"{side}_account"
    raw_id = _clean_saved_account(row.get(id_field, ""))
    raw_legacy = _clean_saved_account(row.get(legacy_field, ""))
    for value in (raw_id, raw_legacy):
        if not value:
            continue
        resolved = configured_account_key(value)
        if resolved:
            return resolved
    # In the oldest format an empty legacy value represented Main. Preserve
    # that convention, but never convert an unknown non-empty id into Main.
    if not raw_id and not raw_legacy:
        return MAIN_ACCOUNT_KEY
    return raw_id or raw_legacy


def _label_for_transfer_side(row: Mapping[str, Any], side: str) -> str:
    snapshot = _clean_saved_account(row.get(f"{side}_account_name_snapshot", ""))
    if snapshot:
        return snapshot
    key = _key_for_transfer_row(row, side)
    resolved = configured_account_key(key)
    if resolved:
        return account_label_for_key(resolved)
    return key or "Unknown account"


def transfer_rows_for_display() -> list[dict[str, Any]]:
    df = load_all()
    if df.empty:
        return []
    rows: list[dict[str, Any]] = []
    for row in df.to_dict(orient="records"):
        amount = float(row.get("amount", 0.0) or 0.0)
        fee = float(row.get("fee_amount", 0.0) or 0.0)
        row_date = row.get("date")
        from_key = _key_for_transfer_row(row, "from")
        to_key = _key_for_transfer_row(row, "to")
        rows.append({
            "id": row.get("id", ""),
            "transfer_uid": row.get("transfer_uid", ""),
            "date_str": row_date.strftime("%Y-%m-%d") if hasattr(row_date, "strftime") and not pd.isna(row_date) else str(row_date or ""),
            "from_account_id": from_key,
            "to_account_id": to_key,
            "from_account": _clean_saved_account(row.get("from_account", "")),
            "to_account": _clean_saved_account(row.get("to_account", "")),
            "from_label": _label_for_transfer_side(row, "from"),
            "to_label": _label_for_transfer_side(row, "to"),
            "amount": f"{amount:.2f}",
            "fee_amount": f"{fee:.2f}",
            "fee_payment_method_id": row.get("fee_payment_method_id", ""),
            "transfer_kind": row.get("transfer_kind") or "normal_transfer",
            "status": row.get("status") or "posted",
            "description": "" if str(row.get("description", "")) == "nan" else str(row.get("description", "") or ""),
        })
    return rows


def totals() -> dict[str, Any]:
    df = load_all()
    if df.empty:
        return {"count": 0, "main_in": 0.0, "main_out": 0.0, "auxiliary_moved": 0.0, "fees": 0.0}
    main_in = 0.0
    main_out = 0.0
    auxiliary_moved = 0.0
    fees = 0.0
    for row in df.to_dict(orient="records"):
        amount = float(row.get("amount", 0.0) or 0.0)
        from_key = _key_for_transfer_row(row, "from")
        to_key = _key_for_transfer_row(row, "to")
        if from_key == MAIN_ACCOUNT_KEY:
            main_out += amount
        if to_key == MAIN_ACCOUNT_KEY:
            main_in += amount
        if from_key != MAIN_ACCOUNT_KEY or to_key != MAIN_ACCOUNT_KEY:
            auxiliary_moved += amount
        fees += float(row.get("fee_amount", 0.0) or 0.0)
    return {"count": int(len(df)), "main_in": main_in, "main_out": main_out, "auxiliary_moved": auxiliary_moved, "fees": fees}


def page_context(error: str = "", message: str = "") -> dict[str, Any]:
    page_errors: list[str] = []
    try:
        choices = account_choices()
    except Exception as exc:
        choices = []
        page_errors.append(f"Could not load account choices: {exc}")
    try:
        balances = account_balances_for_form()
    except Exception as exc:
        balances = {str(row.get("key") or ""): 0.0 for row in choices}
        page_errors.append(f"Could not calculate all account balances: {exc}")
    try:
        method_options = payment_method_options_for_forms()
    except Exception as exc:
        method_options = []
        page_errors.append(f"Could not load fee payment methods: {exc}")
    try:
        transfer_rows = transfer_rows_for_display()
    except Exception as exc:
        transfer_rows = []
        page_errors.append(f"Could not load the existing transfer log: {exc}")
    try:
        transfer_totals = totals()
    except Exception as exc:
        transfer_totals = {"count": 0, "main_in": 0.0, "main_out": 0.0, "auxiliary_moved": 0.0, "fees": 0.0}
        page_errors.append(f"Could not calculate transfer totals: {exc}")

    return {
        "today": date.today().isoformat(),
        "account_options": choices,
        "account_balances": balances,
        "payment_method_options": method_options,
        "transfer_kind_options": sorted(TRANSFER_KIND_OPTIONS),
        "transfers": transfer_rows,
        "totals": transfer_totals,
        "error": " ".join(part for part in [error, *page_errors] if part),
        "message": message,
    }


def main_account_transfer_movements() -> pd.DataFrame:
    """Synthetic rows that affect main-bank net without being income/expense.

    These legacy synthetic rows stay in place until Prompt 11F moves dashboard
    math fully onto the ledger.
    """
    df = load_all()
    if df.empty:
        return _empty_frame()

    rows: list[dict[str, Any]] = []
    for row in df.to_dict(orient="records"):
        amount = float(row.get("amount", 0.0) or 0.0)
        from_key = _key_for_transfer_row(row, "from")
        to_key = _key_for_transfer_row(row, "to")
        if from_key != MAIN_ACCOUNT_KEY and to_key != MAIN_ACCOUNT_KEY:
            continue
        signed = amount if to_key == MAIN_ACCOUNT_KEY else -amount
        rows.append(_movement_row(row, MAIN_ACCOUNT_KEY, MAIN_ACCOUNT_LABEL, signed, "Main bank transfer"))
    return _frame_from_rows(rows)


def auxiliary_transfer_movements(account_key: str | None = None) -> pd.DataFrame:
    """Synthetic account movements for configured non-main accounts."""
    df = load_all()
    if df.empty:
        return _empty_frame()

    rows: list[dict[str, Any]] = []
    for row in df.to_dict(orient="records"):
        amount = float(row.get("amount", 0.0) or 0.0)
        from_key = _key_for_transfer_row(row, "from")
        to_key = _key_for_transfer_row(row, "to")
        if from_key != MAIN_ACCOUNT_KEY:
            rows.append(_movement_row(row, from_key, account_label_for_key(from_key), -amount, "Transfer out"))
        if to_key != MAIN_ACCOUNT_KEY:
            rows.append(_movement_row(row, to_key, account_label_for_key(to_key), amount, "Transfer in"))

    frame = _frame_from_rows(rows)
    if account_key and not frame.empty:
        frame = frame[frame["account_key"] == _account_key_from_value(account_key)].copy()
    return frame


def _movement_row(row: Mapping[str, Any], account_key: str, account_label: str, signed: float, source_label: str) -> dict[str, Any]:
    amount = abs(float(row.get("amount", 0.0) or 0.0))
    from_label = _label_for_transfer_side(row, "from")
    to_label = _label_for_transfer_side(row, "to")
    description = str(row.get("description", "") or "").strip()
    route = f"{from_label} → {to_label}"
    return {
        "id": f"transfer-{row.get('id', '')}",
        "date": row.get("date"),
        "category": "Internal transfer",
        "sub_category": route,
        "amount": amount,
        "account": account_label,
        "description": f"{route}. {description}".strip(),
        "created_at": row.get("created_at"),
        "type": "transfer",
        "signed_amount": signed,
        "account_key": account_key,
        "account_label": account_label,
        "account_route_source": "internal_transfer",
        "account_signed_amount": signed,
        "source": "internal_transfer",
        "source_label": source_label,
        "source_url_kind": "internal_transfer",
        "source_row_index": row.get("id", ""),
        "direction": "in" if signed >= 0 else "out",
        "is_auxiliary_account": account_key != MAIN_ACCOUNT_KEY,
    }


def _frame_from_rows(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return _empty_frame()
    frame = pd.DataFrame(rows)
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["created_at"] = pd.to_datetime(frame["created_at"], errors="coerce")
    frame["amount"] = pd.to_numeric(frame["amount"], errors="coerce").fillna(0.0)
    frame["signed_amount"] = pd.to_numeric(frame["signed_amount"], errors="coerce").fillna(0.0)
    frame["account_signed_amount"] = pd.to_numeric(frame["account_signed_amount"], errors="coerce").fillna(0.0)
    return frame


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=[
        "id", "date", "category", "sub_category", "amount", "account", "description", "created_at",
        "type", "signed_amount", "account_key", "account_label", "account_route_source",
        "account_signed_amount", "source", "source_label", "source_url_kind", "source_row_index",
        "direction", "is_auxiliary_account",
    ])
