from __future__ import annotations

from datetime import datetime

from money_manager.config import PAYABLES_CSV
from money_manager.domain.constants import PAYABLE_FIELDS
from money_manager.repositories.csv_files import append_row, next_numeric_id, read_rows, write_rows


def load_payables() -> list[dict]:
    return [_normalize_payable(row) for row in read_rows(PAYABLES_CSV, PAYABLE_FIELDS)]


def write_payables(rows: list[dict]) -> None:
    write_rows(PAYABLES_CSV, PAYABLE_FIELDS, [_normalize_payable(row) for row in rows])


def append_payable(data: dict) -> int:
    rows = load_payables()
    amount = _amount(data.get("original_amount"))
    remaining = _amount(data.get("remaining_amount", amount)) or amount
    row_id = next_numeric_id(rows)
    row = {
        "id": row_id,
        "name": data.get("name", ""),
        "payee": data.get("payee", ""),
        "original_amount": amount,
        "remaining_amount": remaining,
        "category": data.get("category", "Payable"),
        "account": data.get("account", ""),
        "start_date": data.get("start_date", ""),
        "due_date": data.get("due_date", ""),
        "description": data.get("description", ""),
        "status": data.get("status", "active"),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "closed_at": "",
    }
    append_row(PAYABLES_CSV, PAYABLE_FIELDS, row)
    return int(row_id)


def update_payable(payable_id: int, updates: dict) -> None:
    rows = load_payables()
    for row in rows:
        if str(row.get("id")) != str(payable_id):
            continue
        for key in [
            "name",
            "payee",
            "category",
            "account",
            "start_date",
            "due_date",
            "description",
            "status",
            "closed_at",
        ]:
            if key in updates:
                row[key] = updates[key]
        for key in ["original_amount", "remaining_amount"]:
            if key in updates:
                row[key] = _amount(updates[key])
        break
    write_payables(rows)


def delete_payable(payable_id: int) -> None:
    rows = [row for row in load_payables() if str(row.get("id")) != str(payable_id)]
    write_payables(rows)


def _amount(value) -> float:
    try:
        return max(0.0, float(str(value or 0).replace(",", ".")))
    except (TypeError, ValueError):
        return 0.0


def _normalize_payable(row: dict) -> dict:
    normalized = {field: row.get(field, "") for field in PAYABLE_FIELDS}
    normalized["original_amount"] = _amount(normalized.get("original_amount"))
    normalized["remaining_amount"] = _amount(normalized.get("remaining_amount"))
    if not normalized.get("category"):
        normalized["category"] = "Payable"
    if not normalized["status"]:
        normalized["status"] = "active" if normalized["remaining_amount"] > 0 else "paid"
    return normalized
