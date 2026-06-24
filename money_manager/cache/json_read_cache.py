from __future__ import annotations

import copy
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from money_manager.cache import request_cache
from money_manager.config.user_paths import normalize_user_id

_MAX_ENTRIES = int(os.environ.get("MONEY_MANAGER_JSON_OBJECT_CACHE_ENTRIES", "256") or 256)
_TTL_SECONDS = float(os.environ.get("MONEY_MANAGER_JSON_OBJECT_CACHE_TTL_SECONDS", "1800") or 1800)
_SAFE_COPIES = os.environ.get("MONEY_MANAGER_JSON_OBJECT_SAFE_COPIES", "1").strip() != "0"
_LOCK = threading.RLock()
_SENTINEL = object()


@dataclass
class JsonObjectEntry:
    key: str
    user_id: str
    path: str
    value: Any
    created_at: float
    hits: int = 0


_ENTRIES: "OrderedDict[str, JsonObjectEntry]" = OrderedDict()


def get(path: str | os.PathLike[str], *, user_id: str | None = None) -> Any:
    key = _key(Path(path), user_id=user_id)
    if key is None:
        return _SENTINEL
    request_key = "json_object:" + key
    request_value = request_cache.get(request_key, _SENTINEL)
    if request_value is not _SENTINEL:
        return _clone(request_value)
    now = time.time()
    with _LOCK:
        entry = _ENTRIES.get(key)
        if entry is None:
            return _SENTINEL
        if _TTL_SECONDS > 0 and now - entry.created_at > _TTL_SECONDS:
            _ENTRIES.pop(key, None)
            return _SENTINEL
        entry.hits += 1
        _ENTRIES.move_to_end(key)
        value = _clone(entry.value)
    request_cache.set(request_key, _clone(value))
    return value


def set_value(path: str | os.PathLike[str], value: Any, *, user_id: str | None = None) -> None:
    key = _key(Path(path), user_id=user_id)
    if key is None:
        return
    safe_id = normalize_user_id(user_id) if user_id else ""
    entry = JsonObjectEntry(
        key=key,
        user_id=safe_id,
        path=_path_text(Path(path)),
        value=_clone(value),
        created_at=time.time(),
    )
    with _LOCK:
        _ENTRIES[key] = entry
        _ENTRIES.move_to_end(key)
        while len(_ENTRIES) > _MAX_ENTRIES:
            _ENTRIES.popitem(last=False)
    request_cache.set("json_object:" + key, _clone(value))


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
            _ENTRIES.pop(key, None)
            removed += 1
    request_cache.delete_prefix("json_object:")
    return removed


def clear_user(user_id: str | None = None) -> int:
    safe_id = normalize_user_id(user_id) if user_id else ""
    removed = 0
    with _LOCK:
        for key, entry in list(_ENTRIES.items()):
            if safe_id and entry.user_id != safe_id:
                continue
            _ENTRIES.pop(key, None)
            removed += 1
    request_cache.delete_prefix("json_object:")
    return removed


def stats() -> dict[str, Any]:
    with _LOCK:
        return {"entry_count": len(_ENTRIES), "max_entries": _MAX_ENTRIES, "ttl_seconds": _TTL_SECONDS}


def sentinel() -> object:
    return _SENTINEL


def _key(path: Path, *, user_id: str | None = None) -> str | None:
    try:
        stat = path.stat()
        if not path.is_file():
            return None
        safe_id = normalize_user_id(user_id) if user_id else ""
        return f"{safe_id}:{_path_text(path)}:{int(stat.st_mtime_ns)}:{int(stat.st_size)}"
    except OSError:
        return None


def _path_text(path: Path) -> str:
    try:
        return str(path.resolve())
    except Exception:
        return str(path.absolute())


def _clone(value: Any) -> Any:
    if not _SAFE_COPIES:
        return value
    try:
        return copy.deepcopy(value)
    except Exception:
        try:
            return copy.copy(value)
        except Exception:
            return value
