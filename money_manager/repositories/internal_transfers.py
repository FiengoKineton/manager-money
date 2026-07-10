from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any

import pandas as pd

from money_manager.domain.constants import INTERNAL_TRANSFER_FIELDS
from money_manager.config.user_paths import get_user_data_dir
from money_manager.security.secure_storage import read_json_secure
from money_manager.services.account_config_service import MAIN_ACCOUNT_KEY, configured_account_key
from money_manager.repositories.yearly_partitioned import (
    YearlyDatasetSpec,
    append_partitioned_row,
    ensure_partitioned,
    load_summary,
    mutate_partitioned_row,
    next_partitioned_id,
    read_partitioned_rows,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalise_legacy_row(row: dict[str, Any]) -> dict[str, Any]:
    """Return one transfer row in the current schema without mutating storage.

    Some installations still have the pre-ledger transfer CSV headers.  Reading
    those rows into a DataFrame used to omit ``date`` entirely and crash both the
    transfer page and every balance calculation that includes transfers.  Keep
    the migration read-only here: missing fields receive safe defaults and known
    legacy names are copied into their current equivalents.
    """
    source = dict(row or {})
    normalised = {field: source.get(field, "") for field in INTERNAL_TRANSFER_FIELDS}

    aliases = {
        "date": ("transfer_date", "transaction_date", "movement_date"),
        "from_account": ("source_account", "account_from"),
        "to_account": ("destination_account", "account_to"),
        "from_account_id": ("source_account_id",),
        "to_account_id": ("destination_account_id",),
        "amount": ("transfer_amount", "value"),
        "fee_amount": ("fee", "commission"),
        "description": ("note", "notes", "memo"),
        "created_at": ("created", "timestamp"),
        "updated_at": ("updated",),
    }
    for target, candidates in aliases.items():
        if str(normalised.get(target) or "").strip():
            continue
        for candidate in candidates:
            value = source.get(candidate, "")
            if str(value or "").strip():
                normalised[target] = value
                break

    # A creation timestamp is the safest display/sort fallback for old rows that
    # never had a dedicated transfer date.  If neither exists, pandas will turn
    # the blank value into NaT and the row remains editable instead of crashing.
    if not str(normalised.get("date") or "").strip():
        normalised["date"] = normalised.get("created_at", "")
    if not str(normalised.get("created_at") or "").strip():
        normalised["created_at"] = normalised.get("date", "")
    if not str(normalised.get("updated_at") or "").strip():
        normalised["updated_at"] = normalised.get("created_at", "")
    return normalised


def _transfer_signed_value(row: dict[str, Any]) -> float:
    # Internal transfers redistribute balances; their all-accounts net is zero.
    return 0.0


def _transfer_account_totals(rows: list[dict[str, Any]], user_id: str | None = None) -> dict[str, float]:
    """Resolve both modern account IDs and legacy account labels exactly once."""
    totals: dict[str, float] = {}
    for row in rows:
        amount = float(_money(row.get("amount", 0.0)))
        for side, multiplier in (("from", -1.0), ("to", 1.0)):
            raw = str(row.get(f"{side}_account_id") or row.get(f"{side}_account") or "").strip()
            key = configured_account_key(raw, user_id=user_id) if raw else MAIN_ACCOUNT_KEY
            # Preserve an unknown historical ID instead of silently charging Main.
            key = key or raw
            if key:
                totals[key] = totals.get(key, 0.0) + multiplier * amount
    return totals


def _account_context_fingerprint(user_id: str | None = None) -> str:
    payload = {
        "summary_logic_version": 1,
        "accounts": read_json_secure(get_user_data_dir(user_id) / "accounts.json", default={}, user_id=user_id),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:24]


INTERNAL_TRANSFERS_SPEC = YearlyDatasetSpec(
    name="internal_transfers",
    legacy_filename="internal_transfers.csv",
    folder_name="internal_transfers",
    file_prefix="internal_transfers",
    fields=tuple(INTERNAL_TRANSFER_FIELDS),
    signed_value=_transfer_signed_value,
    account_totals_for_rows=_transfer_account_totals,
    normalize_row=_normalise_legacy_row,
    context_fingerprint=_account_context_fingerprint,
)


def load_rows(*, start: Any = None, end: Any = None, years: list[int] | None = None, user_id: str | None = None) -> list[dict[str, Any]]:
    return read_partitioned_rows(INTERNAL_TRANSFERS_SPEC, start=start, end=end, years=years, user_id=user_id)


def load_all(*, user_id: str | None = None) -> pd.DataFrame:
    rows = load_rows(user_id=user_id)
    if not rows:
        return pd.DataFrame(columns=INTERNAL_TRANSFER_FIELDS)

    # Explicit columns make the loader safe even when all stored rows came from
    # an old header set and therefore omitted one or more current fields.
    df = pd.DataFrame(rows, columns=INTERNAL_TRANSFER_FIELDS).fillna("")
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    df["fee_amount"] = pd.to_numeric(df["fee_amount"], errors="coerce").fillna(0.0)
    df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")
    df["updated_at"] = pd.to_datetime(df["updated_at"], errors="coerce")
    return df.sort_values(by=["date", "created_at"], ascending=[False, False], na_position="last").reset_index(drop=True)


def find_transfer(transfer_id: int | str, *, user_id: str | None = None) -> dict[str, Any] | None:
    for row in load_rows(user_id=user_id):
        if str(row.get("id")) == str(transfer_id):
            return row
    return None


def append_transfer(data: dict[str, Any]) -> int:
    row_id = next_partitioned_id(INTERNAL_TRANSFERS_SPEC)
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
    append_partitioned_row(INTERNAL_TRANSFERS_SPEC, row)
    return int(row_id)


def update_transfer(transfer_id: int | str, data: dict[str, Any]) -> bool:
    editable = {}
    for field in INTERNAL_TRANSFER_FIELDS:
        if field in {"id", "created_at"} or field not in data:
            continue
        editable[field] = _money(data[field]) if field in {"amount", "fee_amount"} else data.get(field, "")
    editable["updated_at"] = data.get("updated_at") or utc_now()
    return mutate_partitioned_row(
        INTERNAL_TRANSFERS_SPEC,
        lambda row: str(row.get("id")) == str(transfer_id),
        update=editable,
    )


def delete_transfer(transfer_id: int | str) -> bool:
    return mutate_partitioned_row(
        INTERNAL_TRANSFERS_SPEC,
        lambda row: str(row.get("id")) == str(transfer_id),
        delete=True,
    )


def transfer_partition_summary(user_id: str | None = None) -> dict[str, Any]:
    ensure_partitioned(INTERNAL_TRANSFERS_SPEC, user_id=user_id)
    return load_summary(INTERNAL_TRANSFERS_SPEC, user_id=user_id)


def _money(value: Any) -> str:
    try:
        return f"{round(float(str(value or '0').replace(',', '.')), 2):.2f}"
    except (TypeError, ValueError):
        return "0.00"
