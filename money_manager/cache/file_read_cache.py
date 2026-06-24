from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from money_manager.config.user_paths import normalize_user_id

_MAX_ENTRIES = int(os.environ.get("MONEY_MANAGER_FILE_READ_CACHE_ENTRIES", "256") or 256)
_MAX_FILE_BYTES = int(os.environ.get("MONEY_MANAGER_FILE_READ_CACHE_MAX_FILE_BYTES", str(8 * 1024 * 1024)) or (8 * 1024 * 1024))
_MAX_TOTAL_BYTES = int(os.environ.get("MONEY_MANAGER_FILE_READ_CACHE_MAX_TOTAL_BYTES", str(64 * 1024 * 1024)) or (64 * 1024 * 1024))
_TTL_SECONDS = float(os.environ.get("MONEY_MANAGER_FILE_READ_CACHE_TTL_SECONDS", "600") or 600)
_LOCK = threading.RLock()
_SENTINEL = object()


@dataclass
class FileReadEntry:
    key: str
    user_id: str
    path: str
    mtime_ns: int
    size: int
    value: bytes
    created_at: float
    last_used_at: float
    hits: int = 0


_ENTRIES: "OrderedDict[str, FileReadEntry]" = OrderedDict()
_TOTAL_BYTES = 0


def get(path: str | os.PathLike[str], *, user_id: str | None = None) -> bytes | object:
    target = Path(path)
    stat_payload = _stat_payload(target)
    if stat_payload is None:
        return _SENTINEL
    key = _key(target, user_id=user_id, mtime_ns=stat_payload[0], size=stat_payload[1])
    now = time.time()
    with _LOCK:
        entry = _ENTRIES.get(key)
        if entry is None:
            return _SENTINEL
        if now - entry.created_at > _TTL_SECONDS:
            _remove_locked(key)
            return _SENTINEL
        entry.hits += 1
        entry.last_used_at = now
        _ENTRIES.move_to_end(key)
        return entry.value


def set_value(path: str | os.PathLike[str], value: bytes | bytearray | memoryview, *, user_id: str | None = None) -> None:
    global _TOTAL_BYTES
    payload = bytes(value or b"")
    if not payload or len(payload) > _MAX_FILE_BYTES:
        return
    target = Path(path)
    stat_payload = _stat_payload(target)
    if stat_payload is None:
        return
    key = _key(target, user_id=user_id, mtime_ns=stat_payload[0], size=stat_payload[1])
    now = time.time()
    safe_id = normalize_user_id(user_id) if user_id else ""
    entry = FileReadEntry(
        key=key,
        user_id=safe_id,
        path=_path_text(target),
        mtime_ns=stat_payload[0],
        size=stat_payload[1],
        value=payload,
        created_at=now,
        last_used_at=now,
    )
    with _LOCK:
        old = _ENTRIES.pop(key, None)
        if old is not None:
            _TOTAL_BYTES -= len(old.value)
        _ENTRIES[key] = entry
        _TOTAL_BYTES += len(payload)
        _ENTRIES.move_to_end(key)
        _evict_locked()


def invalidate_path(path: str | os.PathLike[str], *, user_id: str | None = None) -> int:
    target_text = _path_text(Path(path))
    safe_id = normalize_user_id(user_id) if user_id else ""
    removed = 0
    with _LOCK:
        for key, entry in list(_ENTRIES.items()):
            if entry.path != target_text:
                continue
            if safe_id and entry.user_id != safe_id:
                continue
            _remove_locked(key)
            removed += 1
    return removed


def clear_user(user_id: str | None = None) -> int:
    safe_id = normalize_user_id(user_id) if user_id else ""
    removed = 0
    with _LOCK:
        for key, entry in list(_ENTRIES.items()):
            if safe_id and entry.user_id != safe_id:
                continue
            _remove_locked(key)
            removed += 1
    return removed


def clear_all() -> int:
    global _TOTAL_BYTES
    with _LOCK:
        removed = len(_ENTRIES)
        _ENTRIES.clear()
        _TOTAL_BYTES = 0
        return removed


def stats() -> dict[str, Any]:
    with _LOCK:
        return {
            "entry_count": len(_ENTRIES),
            "total_bytes": _TOTAL_BYTES,
            "max_entries": _MAX_ENTRIES,
            "max_file_bytes": _MAX_FILE_BYTES,
            "max_total_bytes": _MAX_TOTAL_BYTES,
            "ttl_seconds": _TTL_SECONDS,
            "entries": [
                {
                    "user_id": entry.user_id,
                    "path": entry.path,
                    "size": len(entry.value),
                    "age_seconds": round(time.time() - entry.created_at, 3),
                    "hits": entry.hits,
                }
                for entry in _ENTRIES.values()
            ],
        }


def sentinel() -> object:
    return _SENTINEL


def _remove_locked(key: str) -> None:
    global _TOTAL_BYTES
    entry = _ENTRIES.pop(key, None)
    if entry is not None:
        _TOTAL_BYTES -= len(entry.value)
        if _TOTAL_BYTES < 0:
            _TOTAL_BYTES = 0


def _evict_locked() -> None:
    while len(_ENTRIES) > _MAX_ENTRIES or _TOTAL_BYTES > _MAX_TOTAL_BYTES:
        key, _entry = next(iter(_ENTRIES.items()))
        _remove_locked(key)


def _key(path: Path, *, user_id: str | None, mtime_ns: int, size: int) -> str:
    safe_id = normalize_user_id(user_id) if user_id else ""
    return f"{safe_id}:{_path_text(path)}:{mtime_ns}:{size}"


def _path_text(path: Path) -> str:
    try:
        return str(path.resolve())
    except Exception:
        return str(path.absolute())


def _stat_payload(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
        if not path.is_file():
            return None
        return int(stat.st_mtime_ns), int(stat.st_size)
    except OSError:
        return None
