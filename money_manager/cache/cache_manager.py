from __future__ import annotations

import copy
import importlib
import time
from collections.abc import Callable
from typing import Any

from money_manager.cache import request_cache
from money_manager.cache.cache_keys import build_cache_key, digest_payload
from money_manager.cache.cache_registry import CacheDefinition, get_cache_definition
from money_manager.cache.cache_stats_service import record
from money_manager.cache.cache_store import cache_inventory, read_entry, write_entry
from money_manager.cache.source_fingerprint_service import source_fingerprint
from money_manager.config.user_paths import get_current_user_id, normalize_user_id


def get_or_compute(
    name: str,
    builder: Callable[[], Any],
    *,
    params: dict[str, Any] | None = None,
    user_id: str | None = None,
    extra_fingerprint: dict[str, Any] | None = None,
    allow_stale_on_error: bool = False,
    definition: CacheDefinition | None = None,
) -> Any:
    definition = definition or get_cache_definition(name)
    resolved_user_id = normalize_user_id(user_id or get_current_user_id()) if (user_id or get_current_user_id()) else None
    if not resolved_user_id:
        return builder()

    fingerprint = source_fingerprint(definition.dependencies, user_id=resolved_user_id, extra=extra_fingerprint)
    key = build_cache_key(
        user_id=resolved_user_id,
        name=definition.name,
        version=definition.version,
        params=params or {},
        source_fingerprint=fingerprint,
    )
    request_key = f"cache:{resolved_user_id}:{digest_payload({'key': key})}"
    if definition.request_cache_allowed:
        sentinel = object()
        cached_request_value = request_cache.get(request_key, sentinel)
        if cached_request_value is not sentinel:
            return _safe_copy(cached_request_value)

    cached_value = None
    cached_status = ""
    if definition.disk_cache_allowed:
        hit, cached_value, cached_status = read_entry(key, definition, fingerprint, user_id=resolved_user_id)
        if hit:
            record("hits", user_id=resolved_user_id)
            if definition.request_cache_allowed:
                request_cache.set(request_key, _safe_copy(cached_value))
            return _safe_copy(cached_value)
        record("misses", user_id=resolved_user_id)
        if cached_status in {"stale", "expired"}:
            record("stale_skips", user_id=resolved_user_id)

    started = time.perf_counter()
    try:
        value = builder()
    except Exception as exc:
        record("errors", user_id=resolved_user_id, error=str(exc))
        if allow_stale_on_error and cached_value is not None:
            return _safe_copy(cached_value)
        raise
    compute_time = time.perf_counter() - started
    record("recomputes", user_id=resolved_user_id, compute_time=compute_time)
    if definition.disk_cache_allowed:
        write_entry(key, value, definition, fingerprint, user_id=resolved_user_id)
    if definition.request_cache_allowed:
        request_cache.set(request_key, _safe_copy(value))
    return _safe_copy(value)


def data_fingerprint(*, dependencies: tuple[str, ...] | list[str] | None = None, extra: dict[str, Any] | None = None, user_id: str | None = None) -> dict[str, Any]:
    return source_fingerprint(dependencies or (), user_id=user_id, extra=extra)


def import_callable(import_path: str) -> Callable[..., Any]:
    module_name, attr_name = import_path.rsplit(".", 1)
    module = importlib.import_module(module_name)
    return getattr(module, attr_name)


def rebuild_cache_entry(name: str, *, user_id: str | None = None, params: dict[str, Any] | None = None) -> Any:
    definition = get_cache_definition(name)
    if not definition.rebuild_import_path:
        return None
    func = import_callable(definition.rebuild_import_path)
    return get_or_compute(name, lambda: func(**(params or {})), params=params, user_id=user_id, definition=definition)


def cache_status(user_id: str | None = None) -> dict[str, Any]:
    return cache_inventory(user_id=user_id)


def _safe_copy(value: Any) -> Any:
    try:
        return copy.deepcopy(value)
    except Exception:
        return value
