from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

from money_manager.config.paths import INTERNAL_TRANSFERS_CSV
from money_manager.domain.constants import INTERNAL_TRANSFER_FIELDS
from money_manager.repositories.csv_files import append_row, ensure_csv, next_numeric_id, read_rows, write_rows


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_rows() -> list[dict[str, Any]]:
    return read_rows(INTERNAL_TRANSFERS_CSV, INTERNAL_TRANSFER_FIELDS)


def load_all() -> pd.DataFrame:
    rows = read_rows(INTERNAL_TRANSFERS_CSV, INTERNAL_TRANSFER_FIELDS)
    df = pd.DataFrame(rows).fillna("")
    if df.empty:
        return pd.DataFrame(columns=INTERNAL_TRANSFER_FIELDS)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    if "fee_amount" in df.columns:
        df["fee_amount"] = pd.to_numeric(df["fee_amount"], errors="coerce").fillna(0.0)
    df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")
    if "updated_at" in df.columns:
        df["updated_at"] = pd.to_datetime(df["updated_at"], errors="coerce")
    return df.sort_values(by=["date", "created_at"], ascending=[False, False]).reset_index(drop=True)


def find_transfer(transfer_id: int | str) -> dict[str, Any] | None:
    for row in load_rows():
        if str(row.get("id")) == str(transfer_id):
            return row
    return None


def append_transfer(data: dict[str, Any]) -> int:
    rows = load_rows()
    row_id = next_numeric_id(rows)
    now = utc_now()
    row = {field: "" for field in INTERNAL_TRANSFER_FIELDS}
    row.update({field: data.get(field, "") for field in INTERNAL_TRANSFER_FIELDS if field in data})
    row.update({
        "id": str(row_id),
        "date": data.get("date", ""),
        "from_account": data.get("from_account", ""),
        "to_account": data.get("to_account", ""),
        "from_account_id": data.get("from_account_id", ""),
        "from_account_name_snapshot": data.get("from_account_name_snapshot", ""),
        "to_account_id": data.get("to_account_id", ""),
        "to_account_name_snapshot": data.get("to_account_name_snapshot", ""),
        "amount": _money(data.get("amount", "0")),
        "fee_amount": _money(data.get("fee_amount", "0")),
        "description": data.get("description", ""),
        "status": data.get("status") or "posted",
        "transfer_kind": data.get("transfer_kind") or "normal_transfer",
        "created_at": data.get("created_at") or now,
        "updated_at": data.get("updated_at") or now,
    })
    append_row(INTERNAL_TRANSFERS_CSV, INTERNAL_TRANSFER_FIELDS, row)
    return int(row_id)


def update_transfer(transfer_id: int | str, data: dict[str, Any]) -> bool:
    rows = load_rows()
    changed = False
    editable = [field for field in INTERNAL_TRANSFER_FIELDS if field not in {"id", "created_at"}]
    for row in rows:
        if str(row.get("id")) != str(transfer_id):
            continue
        for field in editable:
            if field in data:
                row[field] = _money(data[field]) if field in {"amount", "fee_amount"} else data.get(field, "")
        row["updated_at"] = data.get("updated_at") or utc_now()
        changed = True
        break
    if changed:
        write_rows(INTERNAL_TRANSFERS_CSV, INTERNAL_TRANSFER_FIELDS, rows)
    return changed


def delete_transfer(transfer_id: int | str) -> bool:
    rows = load_rows()
    kept = [row for row in rows if str(row.get("id")) != str(transfer_id)]
    if len(kept) == len(rows):
        return False
    write_rows(INTERNAL_TRANSFERS_CSV, INTERNAL_TRANSFER_FIELDS, kept)
    return True


def _money(value: Any) -> str:
    try:
        return f"{round(float(str(value or '0').replace(',', '.')), 2):.2f}"
    except (TypeError, ValueError):
        return "0.00"
