from __future__ import annotations

from pathlib import Path
from typing import Iterable

from money_manager.config.user_paths import user_data_path
from money_manager.domain.constants import ACCOUNT_LEDGER_FIELDS
from money_manager.repositories.csv_files import append_row, ensure_csv, read_rows, write_rows


def ledger_path(user_id: str | None = None) -> Path:
    return Path(user_data_path("account_ledger.csv", user_id=user_id))


def ensure_account_ledger_file(user_id: str | None = None) -> Path:
    path = ledger_path(user_id=user_id)
    ensure_csv(path, ACCOUNT_LEDGER_FIELDS)
    return path


def read_ledger_rows(user_id: str | None = None) -> list[dict]:
    return read_rows(ledger_path(user_id=user_id), ACCOUNT_LEDGER_FIELDS)


def write_ledger_rows(rows: Iterable[dict], user_id: str | None = None) -> None:
    write_rows(ledger_path(user_id=user_id), ACCOUNT_LEDGER_FIELDS, rows)


def append_ledger_row(row: dict, user_id: str | None = None) -> None:
    append_row(ledger_path(user_id=user_id), ACCOUNT_LEDGER_FIELDS, row)
