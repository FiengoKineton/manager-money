from datetime import datetime

from money_manager.config import SPARAGNAT_CSV
from money_manager.domain.constants import SPARAGNAT_FIELDS
from money_manager.repositories.csv_files import append_row, next_numeric_id, read_rows, write_rows


def load_entries() -> list[dict]:
    return read_rows(SPARAGNAT_CSV, SPARAGNAT_FIELDS)


def append_entry(entry: dict) -> None:
    rows = load_entries()
    row = {
        "id": next_numeric_id(rows),
        "date": entry.get("date", ""),
        "kind": entry.get("kind", "saved_expense"),
        "person": entry.get("person", ""),
        "category": entry.get("category", ""),
        "amount": entry.get("amount", 0.0),
        "account": entry.get("account", ""),
        "description": entry.get("description", ""),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    append_row(SPARAGNAT_CSV, SPARAGNAT_FIELDS, row)


def delete_entry(entry_id: int) -> None:
    rows = [row for row in load_entries() if str(row.get("id", "")) != str(entry_id)]
    write_rows(SPARAGNAT_CSV, SPARAGNAT_FIELDS, rows)
