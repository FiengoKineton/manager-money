from __future__ import annotations

from datetime import date

import pandas as pd

from money_manager.config import (
    MAIN_ACCOUNT_KEY,
    MAIN_ACCOUNT_LABEL,
    account_label_for_key,
    account_options_for_forms,
    auxiliary_account_keys,
    normalize_account_key,
)
from money_manager.repositories.internal_transfers import append_transfer, delete_transfer, load_all, update_transfer
from money_manager.repositories.transactions import append_transaction
from money_manager.services.transaction_service import account_balance, main_net_for_preview


def account_choices() -> list[dict]:
    """Choices allowed for internal transfers. Credit card is intentionally excluded."""
    return account_options_for_forms(include_credit=False)


def _parse_amount(value) -> float:
    try:
        return round(float(str(value or "0").replace(",", ".")), 2)
    except (TypeError, ValueError):
        return 0.0


def _normalise_form_account(value: str) -> str:
    key = normalize_account_key(value)
    if key == MAIN_ACCOUNT_KEY:
        return ""
    return account_label_for_key(key)


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


def _balance_snapshot_for_form() -> dict:
    """Calculate every account balance from one shared transaction snapshot.

    The Internal Transfers page needs all balances for the "From" dropdown.
    The old implementation called ``load_all()`` once for the main account and
    once for every auxiliary account, which made this page slow even when the
    cache folder existed.  This version reads the cached transaction snapshot
    once, then derives all balances from it in one pass.
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
    for key in auxiliary_account_keys():
        row = rows_by_key.get(key, {})
        balances[key] = round(float(row.get("balance", 0.0) or 0.0), 2)
    return balances


def _available_balance_for_key(account_key: str) -> float:
    key = normalize_account_key(account_key)
    return float(_balance_snapshot_for_form().get(key, 0.0) or 0.0)


def account_balances_for_form() -> dict:
    return _balance_snapshot_for_form()


def _account_key_from_saved(value: str) -> str:
    return normalize_account_key(value)


def validate_transfer(form, check_balance: bool = True) -> tuple[dict | None, str]:
    amount = _parse_amount(form.get("amount", "0"))
    from_account = _normalise_form_account(form.get("from_account", ""))
    to_account = _normalise_form_account(form.get("to_account", ""))
    from_key = _account_key_from_saved(from_account)
    to_key = _account_key_from_saved(to_account)

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

    return {
        "date": _parse_date(form.get("date", "")),
        "from_account": from_account,
        "to_account": to_account,
        "amount": amount,
        "description": str(form.get("description", "") or "").strip(),
    }, ""


def create_transfer(form) -> dict:
    data, error = validate_transfer(form)
    if error:
        return {"ok": False, "error": error}
    transfer_id = append_transfer(data)
    fee_id = _append_prepaid_topup_fee(data, transfer_id)
    message = "Internal transfer saved."
    if fee_id is not None:
        message += " A €1.00 pre-paid top-up fee was added as an expense transaction."
    return {"ok": True, "message": message}


def _append_prepaid_topup_fee(data: dict, transfer_id: int) -> int | None:
    from_key = _account_key_from_saved(data.get("from_account", ""))
    to_key = _account_key_from_saved(data.get("to_account", ""))
    if from_key != MAIN_ACCOUNT_KEY or to_key != "pre_paid_card":
        return None
    return append_transaction({
        "type": "expense",
        "date": data.get("date") or date.today().isoformat(),
        "category": "Bank fees",
        "sub_category": "Pre-paid card top-up fee",
        "amount": 1.0,
        "original_amount": "",
        "original_currency": "EUR",
        "exchange_rate_to_eur": "1.00000000",
        "exchange_correction_to_eur": "0.00000000",
        "exchange_effective_rate_to_eur": "1.00000000",
        "account": "",
        "description": f"Automatic €1 fee for internal transfer #{transfer_id} from Main bank to Pre-paid card.",
    })


def update_transfer_from_form(form) -> dict:
    data, error = validate_transfer(form, check_balance=False)
    if error:
        return {"ok": False, "error": error}
    try:
        transfer_id = int(form.get("id", "0"))
    except ValueError:
        return {"ok": False, "error": "Missing transfer id."}
    update_transfer(transfer_id, data)
    return {"ok": True, "message": "Internal transfer updated."}


def delete_transfer_from_form(form) -> dict:
    try:
        transfer_id = int(form.get("id", "0"))
    except ValueError:
        return {"ok": False, "error": "Missing transfer id."}
    delete_transfer(transfer_id)
    return {"ok": True, "message": "Internal transfer deleted."}


def _clean_saved_account(value) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in {"nan", "none"} else text


def _label_for_saved_account(value: str) -> str:
    key = _account_key_from_saved(value)
    return MAIN_ACCOUNT_LABEL if key == MAIN_ACCOUNT_KEY else account_label_for_key(key)


def transfer_rows_for_display() -> list[dict]:
    df = load_all()
    if df.empty:
        return []
    rows = []
    for row in df.to_dict(orient="records"):
        amount = float(row.get("amount", 0.0) or 0.0)
        from_account = _clean_saved_account(row.get("from_account", ""))
        to_account = _clean_saved_account(row.get("to_account", ""))
        row_date = row.get("date")
        rows.append({
            "id": row.get("id", ""),
            "date_str": row_date.strftime("%Y-%m-%d") if hasattr(row_date, "strftime") and not pd.isna(row_date) else str(row_date or ""),
            "from_account": from_account,
            "to_account": to_account,
            "from_label": _label_for_saved_account(from_account),
            "to_label": _label_for_saved_account(to_account),
            "amount": f"{amount:.2f}",
            "description": "" if str(row.get("description", "")) == "nan" else str(row.get("description", "") or ""),
        })
    return rows


def totals() -> dict:
    df = load_all()
    if df.empty:
        return {"count": 0, "main_in": 0.0, "main_out": 0.0, "auxiliary_moved": 0.0}
    main_in = 0.0
    main_out = 0.0
    auxiliary_moved = 0.0
    for row in df.to_dict(orient="records"):
        amount = float(row.get("amount", 0.0) or 0.0)
        from_key = _account_key_from_saved(row.get("from_account", ""))
        to_key = _account_key_from_saved(row.get("to_account", ""))
        if from_key == MAIN_ACCOUNT_KEY:
            main_out += amount
        if to_key == MAIN_ACCOUNT_KEY:
            main_in += amount
        if from_key in auxiliary_account_keys() or to_key in auxiliary_account_keys():
            auxiliary_moved += amount
    return {"count": int(len(df)), "main_in": main_in, "main_out": main_out, "auxiliary_moved": auxiliary_moved}


def page_context(error: str = "", message: str = "") -> dict:
    return {
        "today": date.today().isoformat(),
        "account_options": account_choices(),
        "account_balances": account_balances_for_form(),
        "transfers": transfer_rows_for_display(),
        "totals": totals(),
        "error": error,
        "message": message,
    }


def main_account_transfer_movements() -> pd.DataFrame:
    """Synthetic rows that affect main-bank net without being income/expense."""
    df = load_all()
    if df.empty:
        return _empty_frame()

    rows = []
    for row in df.to_dict(orient="records"):
        amount = float(row.get("amount", 0.0) or 0.0)
        from_key = _account_key_from_saved(row.get("from_account", ""))
        to_key = _account_key_from_saved(row.get("to_account", ""))
        if from_key != MAIN_ACCOUNT_KEY and to_key != MAIN_ACCOUNT_KEY:
            continue
        signed = amount if to_key == MAIN_ACCOUNT_KEY else -amount
        rows.append(_movement_row(row, MAIN_ACCOUNT_KEY, MAIN_ACCOUNT_LABEL, signed, "Main bank transfer"))
    return _frame_from_rows(rows)


def auxiliary_transfer_movements(account_key: str | None = None) -> pd.DataFrame:
    """Synthetic account movements for Cash Flow / Pre-paid / EdenRed / PayPal etc."""
    df = load_all()
    if df.empty:
        return _empty_frame()

    rows = []
    aux_keys = auxiliary_account_keys()
    for row in df.to_dict(orient="records"):
        amount = float(row.get("amount", 0.0) or 0.0)
        from_key = _account_key_from_saved(row.get("from_account", ""))
        to_key = _account_key_from_saved(row.get("to_account", ""))
        if from_key in aux_keys:
            rows.append(_movement_row(row, from_key, account_label_for_key(from_key), -amount, "Transfer out"))
        if to_key in aux_keys:
            rows.append(_movement_row(row, to_key, account_label_for_key(to_key), amount, "Transfer in"))

    frame = _frame_from_rows(rows)
    if account_key and not frame.empty:
        frame = frame[frame["account_key"] == normalize_account_key(account_key)].copy()
    return frame


def _movement_row(row: dict, account_key: str, account_label: str, signed: float, source_label: str) -> dict:
    amount = abs(float(row.get("amount", 0.0) or 0.0))
    from_label = _label_for_saved_account(row.get("from_account", ""))
    to_label = _label_for_saved_account(row.get("to_account", ""))
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


def _frame_from_rows(rows: list[dict]) -> pd.DataFrame:
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
