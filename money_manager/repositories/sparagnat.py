from datetime import datetime

from money_manager.config import SPARAGNAT_CSV
from money_manager.domain.constants import SPARAGNAT_FIELDS
from money_manager.domain.transaction import make_transaction_uid
from money_manager.repositories.csv_files import append_row, next_numeric_id, read_rows, write_rows


def load_entries() -> list[dict]:
    return read_rows(SPARAGNAT_CSV, SPARAGNAT_FIELDS)


def append_entry(entry: dict) -> None:
    rows = load_entries()
    row_id = next_numeric_id(rows)
    row = {
        "id": row_id,
        "transaction_uid": entry.get("transaction_uid") or make_transaction_uid("sparagnat", row_id),
        "date": entry.get("date", ""),
        "kind": entry.get("kind", "saved_expense"),
        "person": entry.get("person", ""),
        "category": entry.get("category", ""),
        "amount": entry.get("amount", 0.0),
        "account": entry.get("account", ""),
        "account_id": entry.get("account_id", ""),
        "account_name_snapshot": entry.get("account_name_snapshot", ""),
        "payment_method_id": entry.get("payment_method_id", ""),
        "payment_method_name_snapshot": entry.get("payment_method_name_snapshot", ""),
        "description": entry.get("description", ""),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    append_row(SPARAGNAT_CSV, SPARAGNAT_FIELDS, row)


def update_entry(entry_id: int, updates: dict) -> None:
    rows = load_entries()
    for row in rows:
        if str(row.get("id", "")) != str(entry_id):
            continue
        for key in ["date", "kind", "person", "category", "amount", "account", "account_id", "account_name_snapshot", "payment_method_id", "payment_method_name_snapshot", "description"]:
            if key in updates:
                row[key] = updates[key]
        break
    write_rows(SPARAGNAT_CSV, SPARAGNAT_FIELDS, rows)


def delete_entry(entry_id: int) -> None:
    rows = [row for row in load_entries() if str(row.get("id", "")) != str(entry_id)]
    write_rows(SPARAGNAT_CSV, SPARAGNAT_FIELDS, rows)
