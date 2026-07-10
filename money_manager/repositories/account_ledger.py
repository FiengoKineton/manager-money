from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping

from money_manager.domain.constants import ACCOUNT_LEDGER_FIELDS
from money_manager.repositories.yearly_partitioned import (
    YearlyDatasetSpec,
    append_partitioned_row,
    dataset_root,
    ensure_partitioned,
    load_summary,
    read_partitioned_rows,
    replace_partitioned_rows,
)


def _signed(row: Mapping[str, Any]) -> float:
    try:
        return float(str(row.get("signed_amount") or "0").replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def _account_values(row: Mapping[str, Any]) -> Mapping[str, float]:
    account_id = str(row.get("account_id") or "").strip()
    return {account_id: _signed(row)} if account_id else {}


ACCOUNT_LEDGER_SPEC = YearlyDatasetSpec(
    name="account_ledger",
    legacy_filename="account_ledger.csv",
    folder_name="account_ledger",
    file_prefix="account_ledger",
    fields=tuple(ACCOUNT_LEDGER_FIELDS),
    date_field="effective_date",
    signed_value=_signed,
    account_values=_account_values,
)


def ledger_path(user_id: str | None = None) -> Path:
    """Compatibility path: the ledger is now a directory of yearly files."""
    return dataset_root(ACCOUNT_LEDGER_SPEC, user_id=user_id)


def ensure_account_ledger_file(user_id: str | None = None) -> Path:
    ensure_partitioned(ACCOUNT_LEDGER_SPEC, user_id=user_id)
    return ledger_path(user_id=user_id)


def read_ledger_rows(
    user_id: str | None = None,
    *,
    start: Any = None,
    end: Any = None,
    years: list[int] | None = None,
) -> list[dict]:
    return read_partitioned_rows(
        ACCOUNT_LEDGER_SPEC,
        user_id=user_id,
        start=start,
        end=end,
        years=years,
    )


def write_ledger_rows(rows: Iterable[dict], user_id: str | None = None) -> None:
    replace_partitioned_rows(ACCOUNT_LEDGER_SPEC, rows, user_id=user_id)


def append_ledger_row(row: dict, user_id: str | None = None) -> None:
    append_partitioned_row(ACCOUNT_LEDGER_SPEC, row, user_id=user_id)


def account_ledger_partition_summary(user_id: str | None = None) -> dict[str, Any]:
    ensure_partitioned(ACCOUNT_LEDGER_SPEC, user_id=user_id)
    return load_summary(ACCOUNT_LEDGER_SPEC, user_id=user_id)
