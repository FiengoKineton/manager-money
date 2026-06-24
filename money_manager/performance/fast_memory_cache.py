from __future__ import annotations

import copy
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from money_manager.cache import runtime_epoch
from money_manager.cache.cache_invalidation import expand_tags
from money_manager.cache.cache_keys import digest_payload
from money_manager.config.user_paths import get_current_user_id, normalize_user_id
from money_manager.storage.data_file_service import resolve_definition_path
from money_manager.storage.data_registry import all_definitions

try:  # pandas is a normal app dependency; keep imports safe for tooling/tests.
    import pandas as pd  # type: ignore
except Exception:  # pragma: no cover
    pd = None  # type: ignore

_ENABLED = os.environ.get("MONEY_MANAGER_TURBO_MEMORY_CACHE", "1").strip() != "0"
_MAX_ENTRIES = int(os.environ.get("MONEY_MANAGER_TURBO_MEMORY_CACHE_ENTRIES", "256") or 256)
_DEFAULT_TTL_SECONDS = float(os.environ.get("MONEY_MANAGER_TURBO_MEMORY_CACHE_TTL_SECONDS", "3600") or 3600)
_SIGNATURE_TTL_SECONDS = float(os.environ.get("MONEY_MANAGER_TURBO_SIGNATURE_TTL_SECONDS", "5") or 5)

_LOCK = threading.RLock()


@dataclass
class _Entry:
    key: str
    user_id: str
    tags: tuple[str, ...]
    value: Any
    created_at: float
    expires_at: float | None
    hits: int = 0


_ENTRIES: "OrderedDict[str, _Entry]" = OrderedDict()
_SIGNATURES: dict[str, tuple[float, dict[str, Any]]] = {}


def is_enabled() -> bool:
    return _ENABLED


def get_or_compute(
    name: str,
    builder: Callable[[], Any],
    *,
    dependencies: Iterable[str] = (),
    params: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
    user_id: str | None = None,
    ttl_seconds: int | float | None = None,
) -> Any:
    """Fast in-process materialized cache.

    This intentionally avoids encrypted disk cache reads/writes during normal
    navigation. Correctness comes from a cheap file-stat signature plus the
    runtime invalidation epoch. Any write updates file mtime/size and bumps the
    epoch, so stale entries become unreachable immediately.
    """
    if not _ENABLED:
        return builder()

    safe_id = normalize_user_id(user_id or get_current_user_id()) if (user_id or get_current_user_id()) else ""
    if not safe_id:
        return builder()

    tags = tuple(sorted(expand_tags(dependencies)))
    signature = data_signature(tags, user_id=safe_id, extra=extra or {})
    key = digest_payload(
        {
            "kind": "turbo_memory_cache",
            "user_id": safe_id,
            "name": str(name),
            "params": params or {},
            "signature": signature.get("digest"),
        }
    )
    now = time.time()
    with _LOCK:
        entry = _ENTRIES.get(key)
        if entry is not None:
            if entry.expires_at is None or entry.expires_at >= now:
                entry.hits += 1
                _ENTRIES.move_to_end(key)
                return _safe_copy(entry.value)
            _ENTRIES.pop(key, None)

    value = builder()
    ttl = _DEFAULT_TTL_SECONDS if ttl_seconds is None else float(ttl_seconds or 0)
    expires_at = None if ttl <= 0 else time.time() + ttl
    with _LOCK:
        _ENTRIES[key] = _Entry(
            key=key,
            user_id=safe_id,
            tags=tags,
            value=_safe_copy(value),
            created_at=time.time(),
            expires_at=expires_at,
        )
        _ENTRIES.move_to_end(key)
        _evict_locked()
    return _safe_copy(value)


def data_signature(dependencies: Iterable[str], *, user_id: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    safe_id = normalize_user_id(user_id)
    tags = tuple(sorted(expand_tags(dependencies)))
    epoch_value = runtime_epoch.epoch(safe_id, tags)
    base = {"user_id": safe_id, "tags": tags, "epoch": epoch_value, "extra": extra or {}}
    memo_key = digest_payload({"turbo_signature": base})
    now = time.time()
    with _LOCK:
        cached = _SIGNATURES.get(memo_key)
        if cached is not None and now - cached[0] <= _SIGNATURE_TTL_SECONDS:
            return dict(cached[1])

    files: dict[str, dict[str, Any]] = {}
    wanted = set(tags)
    for definition in all_definitions("user"):
        if definition.file_type not in {"csv", "json", "directory", "binary_folder"}:
            continue
        definition_tags = set(definition.invalidation_tags or ()) | {definition.name, definition.relative_path}
        if wanted and not (definition_tags & wanted):
            continue
        try:
            path = resolve_definition_path(definition, user_id=safe_id)
        except Exception:
            path = Path(definition.relative_path)
        files[definition.name] = _fast_path_stat(path, schema_version=definition.schema_version)

    payload = {
        "schema_version": 1,
        "user_id": safe_id,
        "tags": tags,
        "epoch": epoch_value,
        "files": files,
        "extra": extra or {},
    }
    payload["digest"] = digest_payload(payload)
    with _LOCK:
        _SIGNATURES[memo_key] = (now, dict(payload))
        if len(_SIGNATURES) > 2048:
            for old_key in list(_SIGNATURES.keys())[:256]:
                _SIGNATURES.pop(old_key, None)
    return payload


def clear(*, user_id: str | None = None, tags: Iterable[str] | None = None) -> int:
    safe_id = normalize_user_id(user_id) if user_id else ""
    wanted = expand_tags(tags or ())
    removed = 0
    with _LOCK:
        for key, entry in list(_ENTRIES.items()):
            if safe_id and entry.user_id != safe_id:
                continue
            if wanted and not (set(entry.tags) & wanted):
                continue
            _ENTRIES.pop(key, None)
            removed += 1
        if safe_id or wanted:
            _SIGNATURES.clear()
        else:
            _SIGNATURES.clear()
    return removed


def stats() -> dict[str, Any]:
    now = time.time()
    with _LOCK:
        return {
            "enabled": _ENABLED,
            "entry_count": len(_ENTRIES),
            "max_entries": _MAX_ENTRIES,
            "signature_count": len(_SIGNATURES),
            "entries": [
                {
                    "user_id": entry.user_id,
                    "tags": list(entry.tags),
                    "age_seconds": round(now - entry.created_at, 3),
                    "expires_in_seconds": None if entry.expires_at is None else round(entry.expires_at - now, 3),
                    "hits": entry.hits,
                }
                for entry in _ENTRIES.values()
            ],
        }


def _fast_path_stat(path: Path, *, schema_version: int = 1) -> dict[str, Any]:
    try:
        stat = path.stat()
        return {
            "exists": True,
            "mtime_ns": int(stat.st_mtime_ns),
            "size": int(stat.st_size),
            "schema_version": int(schema_version or 1),
            "is_dir": bool(path.is_dir()),
        }
    except Exception:
        return {"exists": False, "mtime_ns": 0, "size": 0, "schema_version": int(schema_version or 1), "is_dir": False}


def _evict_locked() -> None:
    while len(_ENTRIES) > _MAX_ENTRIES:
        _ENTRIES.popitem(last=False)


def _safe_copy(value: Any) -> Any:
    if pd is not None and isinstance(value, pd.DataFrame):
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
