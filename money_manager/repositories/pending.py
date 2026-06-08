from datetime import date

from money_manager.config import PENDING_CSV
from money_manager.domain.constants import PENDING_FIELDS
from money_manager.repositories.csv_files import append_row, next_numeric_id, read_rows, write_rows


def load_pending() -> list[dict]:
    return read_rows(PENDING_CSV, PENDING_FIELDS)


def append_pending(tx: dict, due_date: date) -> None:
    rows = load_pending()
    row = {
        "id": next_numeric_id(rows),
        "type": tx.get("type", "expense"),
        "date_due": due_date.isoformat(),
        "amount": tx.get("amount", 0.0),
        "category": tx.get("category", ""),
        "account": tx.get("account", ""),
        "description": tx.get("description", ""),
        "status": "pending",
        "source": tx.get("source", ""),
        "source_id": tx.get("source_id", ""),
    }
    append_row(PENDING_CSV, PENDING_FIELDS, row)


def mark_executed(tx_id: int) -> None:
    rows = load_pending()
    for row in rows:
        if str(row.get("id", "")) == str(tx_id):
            row["status"] = "executed"
    write_rows(PENDING_CSV, PENDING_FIELDS, rows)


def delete_pending(tx_id: int | str) -> None:
    """Remove one pending/executed payment row from the pending queue CSV."""
    rows = [row for row in load_pending() if str(row.get("id", "")) != str(tx_id)]
    write_rows(PENDING_CSV, PENDING_FIELDS, rows)
