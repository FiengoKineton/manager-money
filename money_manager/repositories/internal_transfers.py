from __future__ import annotations

from datetime import datetime

import pandas as pd

from money_manager.config.paths import INTERNAL_TRANSFERS_CSV
from money_manager.domain.constants import INTERNAL_TRANSFER_FIELDS
from money_manager.repositories.csv_files import append_row, ensure_csv, next_numeric_id, read_rows, write_rows


def load_rows() -> list[dict]:
    return read_rows(INTERNAL_TRANSFERS_CSV, INTERNAL_TRANSFER_FIELDS)


def load_all() -> pd.DataFrame:
    ensure_csv(INTERNAL_TRANSFERS_CSV, INTERNAL_TRANSFER_FIELDS)
    df = pd.read_csv(INTERNAL_TRANSFERS_CSV, dtype=str)
    if df.empty:
        return pd.DataFrame(columns=INTERNAL_TRANSFER_FIELDS)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")
    return df.sort_values(by=["date", "created_at"], ascending=[False, False]).reset_index(drop=True)


def append_transfer(data: dict) -> int:
    rows = load_rows()
    row_id = next_numeric_id(rows)
    row = {
        "id": row_id,
        "date": data.get("date", ""),
        "from_account": data.get("from_account", ""),
        "to_account": data.get("to_account", ""),
        "amount": str(data.get("amount", "0")),
        "description": data.get("description", ""),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    append_row(INTERNAL_TRANSFERS_CSV, INTERNAL_TRANSFER_FIELDS, row)
    return int(row_id)


def update_transfer(transfer_id: int, data: dict) -> bool:
    rows = load_rows()
    changed = False
    for row in rows:
        if str(row.get("id")) != str(transfer_id):
            continue
        for field in ["date", "from_account", "to_account", "amount", "description"]:
            if field in data:
                row[field] = data.get(field, "")
        changed = True
        break
    if changed:
        write_rows(INTERNAL_TRANSFERS_CSV, INTERNAL_TRANSFER_FIELDS, rows)
    return changed


def delete_transfer(transfer_id: int) -> bool:
    rows = load_rows()
    kept = [row for row in rows if str(row.get("id")) != str(transfer_id)]
    if len(kept) == len(rows):
        return False
    write_rows(INTERNAL_TRANSFERS_CSV, INTERNAL_TRANSFER_FIELDS, kept)
    return True
