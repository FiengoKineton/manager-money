from datetime import datetime

from money_manager.config import PARENT_SUPPORT_CSV
from money_manager.domain.constants import PARENT_SUPPORT_FIELDS
from money_manager.repositories.csv_files import append_row, next_numeric_id, read_rows, write_rows


def load_entries() -> list[dict]:
    return read_rows(PARENT_SUPPORT_CSV, PARENT_SUPPORT_FIELDS)


def append_entry(entry: dict) -> None:
    rows = load_entries()
    row = {
        "id": next_numeric_id(rows),
        "date": entry.get("date", ""),
        "kind": entry.get("kind", "direct_money"),
        "parent": entry.get("parent", ""),
        "category": entry.get("category", ""),
        "amount": entry.get("amount", 0.0),
        "payment_method": entry.get("payment_method", ""),
        "description": entry.get("description", ""),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    append_row(PARENT_SUPPORT_CSV, PARENT_SUPPORT_FIELDS, row)


def delete_entry(entry_id: int) -> None:
    rows = [row for row in load_entries() if str(row.get("id", "")) != str(entry_id)]
    write_rows(PARENT_SUPPORT_CSV, PARENT_SUPPORT_FIELDS, rows)
