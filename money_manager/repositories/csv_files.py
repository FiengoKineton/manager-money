from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from money_manager.cache import request_cache
from money_manager.config.user_paths import get_current_user_id, normalize_user_id
from money_manager.security.secure_storage import (
    append_csv_row_secure,
    ensure_csv_secure,
    read_csv_secure,
    write_csv_secure,
)

_ROW_CACHE_MAX_ENTRIES = int(os.environ.get("MONEY_MANAGER_ROW_CACHE_ENTRIES", "512") or 512)
_SAFE_ROW_COPIES = os.environ.get("MONEY_MANAGER_ROW_CACHE_SAFE_COPIES", "0").strip() == "1"
_ROW_CACHE_LOCK = threading.RLock()


@dataclass
class _RowCacheEntry:
    key: str
    user_id: str
    path: str
    rows: list[dict]
    created_at: float
    hits: int = 0


_ROW_CACHE: "OrderedDict[str, _RowCacheEntry]" = OrderedDict()


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
    """Read CSV rows with cross-request parsed-row caching.

    secure_storage already caches decrypted bytes, but parsing the same CSV into
    dictionaries on every request still costs time.  This cache is keyed by
    user + absolute path + mtime + size, so a write automatically makes the old
    parsed rows unreachable without expensive hashing.
    """
    user_id = normalize_user_id(get_current_user_id()) if get_current_user_id() else ""
    key = _row_cache_key(path, user_id=user_id)

    sentinel = object()
    request_value = request_cache.get(key, sentinel)
    if request_value is not sentinel:
        return _clone_rows(request_value)

    cached = _row_cache_get(key)
    if cached is not None:
        request_cache.set(key, _clone_rows(cached))
        return _clone_rows(cached)

    rows = read_csv_secure(path, fieldnames)
    clean_rows = [dict(row) for row in rows]
    request_cache.set(key, _clone_rows(clean_rows))
    _row_cache_set(key, path=path, user_id=user_id, rows=clean_rows)
    return _clone_rows(clean_rows)


def write_rows(path: Path, fieldnames: list[str], rows: Iterable[dict]) -> None:
    # secure_storage performs the authoritative cache invalidation after the
    # atomic write.  Calling it again here doubled version bumps, disk-index
    # writes and process-cache clears for every CSV mutation.
    write_csv_secure(path, fieldnames, rows)
    _invalidate_row_cache_for_path(path)
    request_cache.clear_user()


def append_row(path: Path, fieldnames: list[str], row: dict) -> None:
    append_csv_row_secure(path, fieldnames, row)
    _invalidate_row_cache_for_path(path)
    request_cache.clear_user()


def next_numeric_id(rows: list[dict], field: str = "id") -> int:
    ids = [int(row[field]) for row in rows if str(row.get(field, "")).isdigit()]
    return max(ids, default=0) + 1


def row_cache_stats() -> dict:
    with _ROW_CACHE_LOCK:
        return {
            "entry_count": len(_ROW_CACHE),
            "max_entries": _ROW_CACHE_MAX_ENTRIES,
            "safe_row_copies": _SAFE_ROW_COPIES,
            "entries": [
                {
                    "user_id": entry.user_id,
                    "path": entry.path,
                    "rows": len(entry.rows),
                    "age_seconds": round(time.time() - entry.created_at, 3),
                    "hits": entry.hits,
                }
                for entry in _ROW_CACHE.values()
            ],
        }


def clear_row_cache(user_id: str | None = None) -> int:
    safe_id = normalize_user_id(user_id) if user_id else ""
    removed = 0
    with _ROW_CACHE_LOCK:
        for key, entry in list(_ROW_CACHE.items()):
            if safe_id and entry.user_id != safe_id:
                continue
            _ROW_CACHE.pop(key, None)
            removed += 1
    return removed


def _row_cache_get(key: str) -> list[dict] | None:
    with _ROW_CACHE_LOCK:
        entry = _ROW_CACHE.get(key)
        if entry is None:
            return None
        entry.hits += 1
        _ROW_CACHE.move_to_end(key)
        return _clone_rows(entry.rows)


def _row_cache_set(key: str, *, path: Path, user_id: str, rows: list[dict]) -> None:
    with _ROW_CACHE_LOCK:
        _ROW_CACHE[key] = _RowCacheEntry(
            key=key,
            user_id=user_id,
            path=_path_text(path),
            rows=_clone_rows(rows),
            created_at=time.time(),
        )
        _ROW_CACHE.move_to_end(key)
        while len(_ROW_CACHE) > _ROW_CACHE_MAX_ENTRIES:
            _ROW_CACHE.popitem(last=False)


def _invalidate_row_cache_for_path(path: Path, user_id: str | None = None) -> int:
    target_text = _path_text(path)
    safe_id = normalize_user_id(user_id) if user_id else ""
    removed = 0
    with _ROW_CACHE_LOCK:
        for key, entry in list(_ROW_CACHE.items()):
            if entry.path != target_text:
                continue
            if safe_id and entry.user_id != safe_id:
                continue
            _ROW_CACHE.pop(key, None)
            removed += 1
    return removed


def _row_cache_key(path: Path, *, user_id: str) -> str:
    try:
        stat = path.stat()
        mtime_ns = int(stat.st_mtime_ns)
        size = int(stat.st_size)
        exists = path.is_file()
    except OSError:
        mtime_ns = 0
        size = 0
        exists = False
    return f"csv_rows_v2:{user_id}:{_path_text(path)}:{int(exists)}:{mtime_ns}:{size}"


def _path_text(path: Path) -> str:
    try:
        return str(path.resolve())
    except Exception:
        return str(path.absolute())


def _clone_rows(rows: Iterable[dict] | list[dict]) -> list[dict]:
    if _SAFE_ROW_COPIES:
        return [dict(row) for row in rows]
    # Fast mode: copy the list wrapper only. Rows are treated as immutable by
    # read paths; write paths invalidate caches immediately after persisting.
    return list(rows)
