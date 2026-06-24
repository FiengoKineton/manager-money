from __future__ import annotations

import copy
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from money_manager.cache import request_cache
from money_manager.cache.cache_invalidation import expand_tags
from money_manager.cache.cache_keys import digest_payload
from money_manager.config.user_paths import get_current_user_id, normalize_user_id
from money_manager.performance import turbo_version_service

try:  # pandas is a normal app dependency; keep imports safe for tooling/tests.
    import pandas as pd  # type: ignore
except Exception:  # pragma: no cover
    pd = None  # type: ignore

_ENABLED = os.environ.get("MONEY_MANAGER_TURBO_MEMORY_CACHE", "1").strip() != "0"
_MAX_ENTRIES = int(os.environ.get("MONEY_MANAGER_TURBO_MEMORY_CACHE_ENTRIES", "512") or 512)
_DEFAULT_TTL_SECONDS = float(os.environ.get("MONEY_MANAGER_TURBO_MEMORY_CACHE_TTL_SECONDS", "7200") or 7200)
_REQUEST_MEMO_ENABLED = os.environ.get("MONEY_MANAGER_TURBO_REQUEST_MEMO", "1").strip() != "0"
_SINGLE_FLIGHT_ENABLED = os.environ.get("MONEY_MANAGER_TURBO_SINGLE_FLIGHT", "1").strip() != "0"
_COPY_MODE = os.environ.get("MONEY_MANAGER_TURBO_COPY_MODE", "shallow").strip().lower()
_LOCK = threading.RLock()


@dataclass
class _Entry:
    key: str
    user_id: str
    name: str
    params_digest: str
    tags: tuple[str, ...]
    value: Any
    created_at: float
    expires_at: float | None
    hits: int = 0


_ENTRIES: "OrderedDict[str, _Entry]" = OrderedDict()
_BUILD_LOCKS: dict[str, threading.Lock] = {}
_STATS = {"hits": 0, "misses": 0, "builds": 0, "request_hits": 0, "singleflight_waits": 0, "sets": 0}


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
    """Professional hot-path materialized cache.

    The cache key uses a runtime data-version signature instead of repeatedly
    hashing or statting data files. Writes through the app bump the version
    immediately; external file edits are detected by the throttled poller in
    turbo_version_service.
    """
    if not _ENABLED:
        return builder()

    safe_id = normalize_user_id(user_id or get_current_user_id()) if (user_id or get_current_user_id()) else ""
    if not safe_id:
        return builder()

    params_payload = params or {}
    extra_payload = extra or {}
    tags = tuple(sorted(expand_tags(dependencies)))
    signature = data_signature(tags, user_id=safe_id, extra=extra_payload)
    params_digest = digest_payload(params_payload)
    key = digest_payload(
        {
            "kind": "turbo_memory_cache_v3",
            "user_id": safe_id,
            "name": str(name),
            "params_digest": params_digest,
            "signature": signature.get("digest"),
        }
    )

    request_key = "turbo_memory:" + key
    if _REQUEST_MEMO_ENABLED:
        sentinel = object()
        request_value = request_cache.get(request_key, sentinel)
        if request_value is not sentinel:
            _record("request_hits")
            return _safe_copy(request_value)

    cached = _get_entry_value(key)
    if cached is not None:
        if _REQUEST_MEMO_ENABLED:
            request_cache.set(request_key, _safe_copy(cached))
        return cached

    if not _SINGLE_FLIGHT_ENABLED:
        return _build_and_store(key, name, params_digest, tags, builder, safe_id, ttl_seconds, request_key)

    build_lock = _lock_for_key(key)
    acquired = build_lock.acquire(blocking=False)
    if not acquired:
        _record("singleflight_waits")
        with build_lock:
            cached_after_wait = _get_entry_value(key)
            if cached_after_wait is not None:
                if _REQUEST_MEMO_ENABLED:
                    request_cache.set(request_key, _safe_copy(cached_after_wait))
                return cached_after_wait
            return _build_and_store(key, name, params_digest, tags, builder, safe_id, ttl_seconds, request_key)
    try:
        cached_after_lock = _get_entry_value(key)
        if cached_after_lock is not None:
            if _REQUEST_MEMO_ENABLED:
                request_cache.set(request_key, _safe_copy(cached_after_lock))
            return cached_after_lock
        return _build_and_store(key, name, params_digest, tags, builder, safe_id, ttl_seconds, request_key)
    finally:
        try:
            build_lock.release()
        except RuntimeError:
            pass
        _cleanup_build_locks()


def data_signature(dependencies: Iterable[str], *, user_id: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    return turbo_version_service.signature(dependencies, user_id=user_id, extra=extra or {})


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
    try:
        turbo_version_service.clear(user_id=safe_id or None, tags=wanted or None)
    except Exception:
        pass
    try:
        if wanted:
            for tag in wanted:
                request_cache.delete_prefix(f"turbo_memory:{safe_id}:{tag}")
        else:
            request_cache.delete_prefix("turbo_memory:")
    except Exception:
        pass
    return removed


def stats() -> dict[str, Any]:
    now = time.time()
    with _LOCK:
        return {
            "enabled": _ENABLED,
            "entry_count": len(_ENTRIES),
            "max_entries": _MAX_ENTRIES,
            "request_memo_enabled": _REQUEST_MEMO_ENABLED,
            "single_flight_enabled": _SINGLE_FLIGHT_ENABLED,
            "copy_mode": _COPY_MODE,
            "stats": dict(_STATS),
            "version_service": turbo_version_service.stats(),
            "entries": [
                {
                    "name": entry.name,
                    "user_id": entry.user_id,
                    "tags": list(entry.tags),
                    "age_seconds": round(now - entry.created_at, 3),
                    "expires_in_seconds": None if entry.expires_at is None else round(entry.expires_at - now, 3),
                    "hits": entry.hits,
                }
                for entry in _ENTRIES.values()
            ],
        }


def _get_entry_value(key: str) -> Any | None:
    now = time.time()
    with _LOCK:
        entry = _ENTRIES.get(key)
        if entry is None:
            _record_locked("misses")
            return None
        if entry.expires_at is not None and entry.expires_at < now:
            _ENTRIES.pop(key, None)
            _record_locked("misses")
            return None
        entry.hits += 1
        _record_locked("hits")
        _ENTRIES.move_to_end(key)
        return _safe_copy(entry.value)


def _build_and_store(
    key: str,
    name: str,
    params_digest: str,
    tags: tuple[str, ...],
    builder: Callable[[], Any],
    safe_id: str,
    ttl_seconds: int | float | None,
    request_key: str,
) -> Any:
    _record("builds")
    value = builder()
    ttl = _DEFAULT_TTL_SECONDS if ttl_seconds is None else float(ttl_seconds or 0)
    expires_at = None if ttl <= 0 else time.time() + ttl
    cached_value = _safe_copy(value)
    with _LOCK:
        _ENTRIES[key] = _Entry(
            key=key,
            user_id=safe_id,
            name=str(name),
            params_digest=params_digest,
            tags=tags,
            value=cached_value,
            created_at=time.time(),
            expires_at=expires_at,
        )
        _ENTRIES.move_to_end(key)
        _record_locked("sets")
        _evict_locked()
    if _REQUEST_MEMO_ENABLED:
        request_cache.set(request_key, _safe_copy(cached_value))
    return _safe_copy(value)


def _lock_for_key(key: str) -> threading.Lock:
    with _LOCK:
        lock = _BUILD_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _BUILD_LOCKS[key] = lock
        return lock


def _cleanup_build_locks() -> None:
    with _LOCK:
        if len(_BUILD_LOCKS) <= 256:
            return
        for key in list(_BUILD_LOCKS.keys())[:64]:
            lock = _BUILD_LOCKS.get(key)
            if lock is not None and not lock.locked():
                _BUILD_LOCKS.pop(key, None)


def _evict_locked() -> None:
    while len(_ENTRIES) > _MAX_ENTRIES:
        _ENTRIES.popitem(last=False)


def _record(name: str) -> None:
    with _LOCK:
        _record_locked(name)


def _record_locked(name: str) -> None:
    _STATS[name] = int(_STATS.get(name, 0)) + 1


def _safe_copy(value: Any) -> Any:
    if _COPY_MODE in {"none", "off", "0"}:
        return value
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
    if _COPY_MODE in {"deep", "safe"}:
        try:
            return copy.deepcopy(value)
        except Exception:
            pass
    try:
        return copy.copy(value)
    except Exception:
        return value
