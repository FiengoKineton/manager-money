from __future__ import annotations

from datetime import datetime

from money_manager.config import RECEIVABLES_CSV
from money_manager.domain.constants import RECEIVABLE_FIELDS
from money_manager.repositories.csv_files import append_row, next_numeric_id, read_rows, write_rows


def load_receivables() -> list[dict]:
    return [_normalize_receivable(row) for row in read_rows(RECEIVABLES_CSV, RECEIVABLE_FIELDS)]


def write_receivables(rows: list[dict]) -> None:
    write_rows(RECEIVABLES_CSV, RECEIVABLE_FIELDS, [_normalize_receivable(row) for row in rows])


def append_receivable(data: dict) -> int:
    rows = load_receivables()
    amount = _amount(data.get("original_amount"))
    remaining = _amount(data.get("remaining_amount", amount)) or amount
    row_id = next_numeric_id(rows)
    row = {
        "id": row_id,
        "name": data.get("name", ""),
        "debtor": data.get("debtor", ""),
        "original_amount": amount,
        "remaining_amount": remaining,
        "account": data.get("account", ""),
        "start_date": data.get("start_date", ""),
        "due_date": data.get("due_date", ""),
        "description": data.get("description", ""),
        "account_id": data.get("account_id", ""),
        "account_name_snapshot": data.get("account_name_snapshot", ""),
        "preferred_payment_method_id": data.get("preferred_payment_method_id", ""),
        "preferred_payment_method_name_snapshot": data.get("preferred_payment_method_name_snapshot", ""),
        "status": data.get("status", "active"),
        "linked_expense_transaction_id": data.get("linked_expense_transaction_id", ""),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "closed_at": "",
    }
    append_row(RECEIVABLES_CSV, RECEIVABLE_FIELDS, row)
    return int(row_id)


def update_receivable(receivable_id: int, updates: dict) -> None:
    rows = load_receivables()
    for row in rows:
        if str(row.get("id")) != str(receivable_id):
            continue
        for key in [
            "name",
            "debtor",
            "account",
            "account_id",
            "account_name_snapshot",
            "preferred_payment_method_id",
            "preferred_payment_method_name_snapshot",
            "start_date",
            "due_date",
            "description",
            "status",
            "linked_expense_transaction_id",
            "closed_at",
        ]:
            if key in updates:
                row[key] = updates[key]
        for key in ["original_amount", "remaining_amount"]:
            if key in updates:
                row[key] = _amount(updates[key])
        break
    write_receivables(rows)


def delete_receivable(receivable_id: int) -> None:
    rows = [row for row in load_receivables() if str(row.get("id")) != str(receivable_id)]
    write_receivables(rows)


def _amount(value) -> float:
    try:
        return max(0.0, float(str(value or 0).replace(",", ".")))
    except (TypeError, ValueError):
        return 0.0


def _normalize_receivable(row: dict) -> dict:
    normalized = {field: row.get(field, "") for field in RECEIVABLE_FIELDS}
    normalized["original_amount"] = _amount(normalized.get("original_amount"))
    normalized["remaining_amount"] = _amount(normalized.get("remaining_amount"))
    if not normalized["status"]:
        normalized["status"] = "active" if normalized["remaining_amount"] > 0 else "collected"
    return normalized
