from __future__ import annotations

import copy
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Iterable

try:  # pandas is an app dependency, but keep cache import safe for tools.
    import pandas as pd  # type: ignore
except Exception:  # pragma: no cover
    pd = None  # type: ignore

_MAX_ENTRIES = int(os.environ.get("MONEY_MANAGER_PROCESS_CACHE_ENTRIES", "192") or 192)
_LOCK = threading.RLock()
_SENTINEL = object()


@dataclass
class ProcessCacheEntry:
    key: str
    user_id: str
    source_digest: str
    tags: tuple[str, ...]
    value: Any
    expires_at: float | None
    created_at: float
    hits: int = 0


_ENTRIES: "OrderedDict[str, ProcessCacheEntry]" = OrderedDict()


def get(key: str, *, user_id: str, source_digest: str) -> Any:
    now = time.time()
    process_key = _process_key(user_id, key)
    with _LOCK:
        entry = _ENTRIES.get(process_key)
        if entry is None:
            return _SENTINEL
        if entry.source_digest != source_digest:
            _ENTRIES.pop(process_key, None)
            return _SENTINEL
        if entry.expires_at is not None and entry.expires_at < now:
            _ENTRIES.pop(process_key, None)
            return _SENTINEL
        entry.hits += 1
        _ENTRIES.move_to_end(process_key)
        return _safe_copy(entry.value)


def set_value(
    key: str,
    value: Any,
    *,
    user_id: str,
    source_digest: str,
    tags: Iterable[str] = (),
    ttl_seconds: int | None = None,
) -> None:
    now = time.time()
    expires_at = None if not ttl_seconds else now + int(ttl_seconds)
    process_key = _process_key(user_id, key)
    entry = ProcessCacheEntry(
        key=key,
        user_id=str(user_id or ""),
        source_digest=str(source_digest or ""),
        tags=tuple(sorted({str(tag) for tag in tags if str(tag or "").strip()})),
        value=_safe_copy(value),
        expires_at=expires_at,
        created_at=now,
    )
    with _LOCK:
        _ENTRIES[process_key] = entry
        _ENTRIES.move_to_end(process_key)
        _evict_locked()


def clear(*, user_id: str | None = None, tags: Iterable[str] | None = None) -> int:
    wanted_tags = {str(tag) for tag in (tags or ()) if str(tag or "").strip()}
    removed = 0
    with _LOCK:
        for process_key, entry in list(_ENTRIES.items()):
            if user_id and entry.user_id != str(user_id):
                continue
            if wanted_tags and not (set(entry.tags) & wanted_tags):
                continue
            _ENTRIES.pop(process_key, None)
            removed += 1
    return removed


def stats() -> dict[str, Any]:
    with _LOCK:
        return {
            "entry_count": len(_ENTRIES),
            "max_entries": _MAX_ENTRIES,
            "entries": [
                {
                    "user_id": entry.user_id,
                    "tags": list(entry.tags),
                    "age_seconds": round(time.time() - entry.created_at, 3),
                    "expires_in_seconds": None if entry.expires_at is None else round(entry.expires_at - time.time(), 3),
                    "hits": entry.hits,
                }
                for entry in _ENTRIES.values()
            ],
        }


def sentinel() -> object:
    return _SENTINEL


def _process_key(user_id: str, key: str) -> str:
    return f"{user_id}:{key}"


def _evict_locked() -> None:
    while len(_ENTRIES) > _MAX_ENTRIES:
        _ENTRIES.popitem(last=False)


def _safe_copy(value: Any) -> Any:
    if pd is not None and isinstance(value, pd.DataFrame):
        # Most callers immediately filter/copy the frame.  A shallow copy avoids
        # duplicating large transaction tables on every route change while still
        # protecting the cached object wrapper from accidental reassignment.
        return value.copy(deep=False)
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return tuple(value)
    if isinstance(value, set):
        return set(value)
    try:
        return copy.copy(value)
    except Exception:
        return value
