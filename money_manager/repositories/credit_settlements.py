from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

from money_manager.config.paths import CREDIT_SETTLEMENTS_CSV
from money_manager.domain.constants import CREDIT_SETTLEMENT_FIELDS
from money_manager.repositories.csv_files import append_row, ensure_csv, next_numeric_id, read_rows, write_rows


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_rows() -> list[dict[str, Any]]:
    return read_rows(CREDIT_SETTLEMENTS_CSV, CREDIT_SETTLEMENT_FIELDS)


def load_all() -> pd.DataFrame:
    rows = read_rows(CREDIT_SETTLEMENTS_CSV, CREDIT_SETTLEMENT_FIELDS)
    df = pd.DataFrame(rows).fillna("")
    if df.empty:
        return pd.DataFrame(columns=CREDIT_SETTLEMENT_FIELDS)
    for column in ["due_date", "created_at", "updated_at", "executed_at"]:
        if column in df.columns:
            df[column] = pd.to_datetime(df[column], errors="coerce")
    if "amount" in df.columns:
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    return df.sort_values(by=["due_date", "created_at"], ascending=[True, False]).reset_index(drop=True)


def append_settlement(data: dict[str, Any]) -> int:
    rows = load_rows()
    row_id = next_numeric_id(rows)
    now = utc_now()
    row = {field: "" for field in CREDIT_SETTLEMENT_FIELDS}
    row.update({field: data.get(field, "") for field in CREDIT_SETTLEMENT_FIELDS if field in data})
    row.update({
        "id": str(row_id),
        "amount": _money(data.get("amount", row.get("amount", "0"))),
        "currency": str(data.get("currency") or row.get("currency") or "EUR").upper(),
        "status": data.get("status") or row.get("status") or "open",
        "created_at": data.get("created_at") or row.get("created_at") or now,
        "updated_at": data.get("updated_at") or row.get("updated_at") or now,
    })
    append_row(CREDIT_SETTLEMENTS_CSV, CREDIT_SETTLEMENT_FIELDS, row)
    return int(row_id)


def update_settlement(settlement_id: str | int, updates: dict[str, Any]) -> bool:
    rows = load_rows()
    changed = False
    for row in rows:
        if str(row.get("id")) != str(settlement_id):
            continue
        for field in CREDIT_SETTLEMENT_FIELDS:
            if field == "id":
                continue
            if field in updates:
                value = updates.get(field, "")
                if field == "amount":
                    value = _money(value)
                row[field] = value
        row["updated_at"] = updates.get("updated_at") or utc_now()
        changed = True
        break
    if changed:
        write_rows(CREDIT_SETTLEMENTS_CSV, CREDIT_SETTLEMENT_FIELDS, rows)
    return changed


def find_by_id(settlement_id: str | int) -> dict[str, Any] | None:
    for row in load_rows():
        if str(row.get("id")) == str(settlement_id):
            return row
    return None


def find_by_uid(settlement_uid: str) -> dict[str, Any] | None:
    wanted = str(settlement_uid or "").strip()
    if not wanted:
        return None
    for row in load_rows():
        if str(row.get("settlement_uid") or "") == wanted:
            return row
    return None


def upsert_by_uid(settlement_uid: str, data: dict[str, Any], *, locked_when_executed: bool = True) -> int:
    existing = find_by_uid(settlement_uid)
    if not existing:
        payload = dict(data)
        payload["settlement_uid"] = settlement_uid
        return append_settlement(payload)
    if locked_when_executed and str(existing.get("status") or "").lower() in {"executed", "cancelled", "adjusted"}:
        return int(existing.get("id") or 0)
    updates = dict(data)
    updates.pop("created_at", None)
    update_settlement(existing.get("id", ""), updates)
    return int(existing.get("id") or 0)


def _money(value: Any) -> str:
    try:
        return f"{round(float(str(value or '0').replace(',', '.')), 2):.2f}"
    except (TypeError, ValueError):
        return "0.00"
