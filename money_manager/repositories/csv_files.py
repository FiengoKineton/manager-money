from __future__ import annotations

from pathlib import Path
from typing import Iterable

from money_manager.cache import request_cache
from money_manager.config.user_paths import get_current_user_id
from money_manager.cache.source_fingerprint_service import fingerprint_for_path

from money_manager.security.secure_storage import (
    append_csv_row_secure,
    ensure_csv_secure,
    read_csv_secure,
    write_csv_secure,
)


def _notify_cache_changed(path: Path | None = None) -> None:
    try:
        from money_manager.services.cache_service import notify_path_changed, notify_data_changed

        if path is not None:
            notify_path_changed(str(path))
        else:
            notify_data_changed()
    except Exception:
        pass


def ensure_csv(path: Path, fieldnames: list[str]) -> None:
    """Create or migrate a CSV file while respecting encryption-at-rest."""
    ensure_csv_secure(path, fieldnames)


def _current_headers(path: Path, fallback: list[str]) -> list[str]:
    rows = read_csv_secure(path, fallback)
    if not rows:
        # ensure_csv_secure already created the file with fallback headers.
        return fallback
    headers = list(rows[0].keys())
    return headers or fallback


def read_rows(path: Path, fieldnames: list[str]) -> list[dict]:
    try:
        fp = fingerprint_for_path(path, user_id=get_current_user_id())
        key = f"csv_rows:{get_current_user_id() or ''}:{path}:{fp.get('mtime_ns')}:{fp.get('size')}:{fp.get('sha256')}"
        sentinel = object()
        cached = request_cache.get(key, sentinel)
        if cached is not sentinel:
            return [dict(row) for row in cached]
        rows = read_csv_secure(path, fieldnames)
        request_cache.set(key, [dict(row) for row in rows])
        return rows
    except Exception:
        return read_csv_secure(path, fieldnames)


def write_rows(path: Path, fieldnames: list[str], rows: Iterable[dict]) -> None:
    write_csv_secure(path, fieldnames, rows)
    request_cache.clear_user()
    _notify_cache_changed(path)


def append_row(path: Path, fieldnames: list[str], row: dict) -> None:
    append_csv_row_secure(path, fieldnames, row)
    request_cache.clear_user()
    _notify_cache_changed(path)


def next_numeric_id(rows: list[dict], field: str = "id") -> int:
    ids = [int(row[field]) for row in rows if str(row.get(field, "")).isdigit()]
    return max(ids, default=0) + 1
