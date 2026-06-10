from __future__ import annotations

from datetime import datetime

from money_manager.config import INVESTMENT_ASSETS_CSV
from money_manager.domain.constants import INVESTMENT_ASSET_FIELDS
from money_manager.repositories.csv_files import append_row, next_numeric_id, read_rows, write_rows

DEFAULT_ASSET = {
    "symbol": "VWCE.MI",
    "label": "Default ETF proxy - edit me",
    "allocation_pct": "100",
    "currency": "EUR",
    "active": "1",
}


def load_investment_assets() -> list[dict]:
    rows = read_rows(INVESTMENT_ASSETS_CSV, INVESTMENT_ASSET_FIELDS)
    if not rows:
        append_investment_asset(DEFAULT_ASSET)
        rows = read_rows(INVESTMENT_ASSETS_CSV, INVESTMENT_ASSET_FIELDS)
    return [_normalize_asset(row) for row in rows]


def write_investment_assets(rows: list[dict]) -> None:
    write_rows(INVESTMENT_ASSETS_CSV, INVESTMENT_ASSET_FIELDS, [_normalize_asset(row) for row in rows])


def append_investment_asset(data: dict) -> None:
    rows = read_rows(INVESTMENT_ASSETS_CSV, INVESTMENT_ASSET_FIELDS)
    row = {
        "id": next_numeric_id(rows),
        "symbol": str(data.get("symbol", "")).strip().upper(),
        "label": str(data.get("label", "")).strip(),
        "allocation_pct": _pct(data.get("allocation_pct", 100)),
        "currency": str(data.get("currency", "EUR") or "EUR").strip().upper(),
        "active": str(data.get("active", "1") or "1"),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    if row["symbol"]:
        append_row(INVESTMENT_ASSETS_CSV, INVESTMENT_ASSET_FIELDS, row)


def delete_investment_asset(asset_id: int) -> None:
    rows = [row for row in load_investment_assets() if str(row.get("id")) != str(asset_id)]
    write_investment_assets(rows)


def update_investment_asset(asset_id: int, updates: dict) -> None:
    rows = load_investment_assets()
    for row in rows:
        if str(row.get("id")) != str(asset_id):
            continue
        for key in ["symbol", "label", "allocation_pct", "currency", "active"]:
            if key in updates:
                row[key] = updates[key]
        break
    write_investment_assets(rows)


def _normalize_asset(row: dict) -> dict:
    normalized = {field: row.get(field, "") for field in INVESTMENT_ASSET_FIELDS}
    normalized["symbol"] = str(normalized.get("symbol", "")).strip().upper()
    normalized["label"] = normalized.get("label") or normalized["symbol"]
    normalized["allocation_pct"] = _pct(normalized.get("allocation_pct"))
    normalized["currency"] = str(normalized.get("currency") or "EUR").strip().upper()
    if normalized.get("active") == "":
        normalized["active"] = "1"
    return normalized


def _pct(value) -> float:
    try:
        return max(0.0, float(str(value or 0).replace(",", ".")))
    except (TypeError, ValueError):
        return 0.0
