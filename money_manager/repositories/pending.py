from datetime import date

from money_manager.config import PENDING_CSV
from money_manager.domain.constants import PENDING_FIELDS
from money_manager.repositories.csv_files import append_row, next_numeric_id, read_rows, write_rows


def load_pending() -> list[dict]:
    return read_rows(PENDING_CSV, PENDING_FIELDS)


def append_pending(tx: dict, due_date: date) -> int | None:
    rows = load_pending()
    row_id = next_numeric_id(rows)
    row = {
        "id": row_id,
        "type": tx.get("type", "expense"),
        "date_due": due_date.isoformat(),
        "amount": tx.get("amount", 0.0),
        "category": tx.get("category", ""),
        "account": tx.get("account", ""),
        "description": tx.get("description", ""),
        "status": tx.get("status", "pending") or "pending",
        "source": tx.get("source", ""),
        "source_id": tx.get("source_id", ""),
        "pending_kind": tx.get("pending_kind", ""),
        "account_key": tx.get("account_key", ""),
        "account_label": tx.get("account_label", ""),
        "statement_month": tx.get("statement_month", ""),
        "date_charge": tx.get("date_charge", ""),
    }
    append_row(PENDING_CSV, PENDING_FIELDS, row)
    return int(row_id)


def write_pending(rows: list[dict]) -> None:
    write_rows(PENDING_CSV, PENDING_FIELDS, rows)


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

def update_pending(tx_id: int | str, updates: dict) -> None:
    rows = load_pending()
    for row in rows:
        if str(row.get("id", "")) != str(tx_id):
            continue
        for key in ["type", "date_due", "amount", "category", "account", "description", "status", "source", "source_id", "pending_kind", "account_key", "account_label", "statement_month", "date_charge"]:
            if key in updates:
                row[key] = updates[key]
        break
    write_rows(PENDING_CSV, PENDING_FIELDS, rows)


def delete_pending_for_source(source: str, source_id: int | str, only_pending: bool = True) -> None:
    rows = []
    for row in load_pending():
        same_source = row.get("source") == source and str(row.get("source_id", "")) == str(source_id)
        if same_source and (not only_pending or row.get("status") == "pending"):
            continue
        rows.append(row)
    write_rows(PENDING_CSV, PENDING_FIELDS, rows)



def delete_pending_for_source_description(source: str, source_id: int | str, description: str, only_pending: bool = True) -> None:
    rows = []
    for row in load_pending():
        same_source = row.get("source") == source and str(row.get("source_id", "")) == str(source_id)
        same_description = row.get("description", "") == description
        if same_source and same_description and (not only_pending or row.get("status") == "pending"):
            continue
        rows.append(row)
    write_rows(PENDING_CSV, PENDING_FIELDS, rows)


def delay_pending(tx_id: int | str, new_due_date: str) -> None:
    """Move a pending payment to a future due date without executing it."""
    if not new_due_date:
        return

    rows = load_pending()
    for row in rows:
        if str(row.get("id", "")) == str(tx_id):
            row["date_due"] = new_due_date
            row["status"] = "pending"
            break
    write_rows(PENDING_CSV, PENDING_FIELDS, rows)
