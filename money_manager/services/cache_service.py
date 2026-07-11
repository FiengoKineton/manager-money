"""Compatibility facade for the professional cache package.

Old imports keep working, but the implementation now lives in
``money_manager.cache`` and stores disposable per-user cache under the external
MoneyManagerData/cache folder.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable, Iterable
from typing import Any

from money_manager.cache.cache_invalidation import invalidate_all, invalidate_tags
from money_manager.cache.cache_manager import cache_status as _cache_status, data_fingerprint as _data_fingerprint, get_or_compute
from money_manager.cache.cache_registry import get_cache_definition
from money_manager.performance import fast_memory_cache
from money_manager.cache.precompute_service import precompute_after_write, precompute_user_dashboard, warm_cache_on_login
from money_manager.cache.source_fingerprint_service import tags_for_path
from money_manager.config.user_paths import get_current_user_id, normalize_user_id, using_user

WARMUP_DEBOUNCE_SECONDS = 0.8
_LOCK = threading.RLock()
_BACKGROUND_TIMERS: dict[str, threading.Timer] = {}
_STARTUP_WARMED: set[str] = set()


def cached_calculation(
    key: str,
    builder: Callable[[], Any],
    *,
    extra_fingerprint: dict[str, Any] | None = None,
    allow_stale_on_error: bool = False,
) -> Any:
    definition = get_cache_definition(key)
    params = {"legacy_key": key, "extra": extra_fingerprint or {}}
    if fast_memory_cache.is_enabled():
        try:
            return fast_memory_cache.get_or_compute(
                key,
                builder,
                dependencies=definition.dependencies,
                params=params,
                extra=extra_fingerprint or {},
                ttl_seconds=definition.ttl_seconds,
            )
        except Exception:
            if not allow_stale_on_error:
                pass
    return get_or_compute(
        key,
        builder,
        params=params,
        extra_fingerprint=extra_fingerprint,
        allow_stale_on_error=allow_stale_on_error,
        definition=definition,
    )


def data_fingerprint(*, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    return _data_fingerprint(extra=extra)


def notify_data_changed(tags: Iterable[str] | None = None, *, user_id: str | None = None, path: str | None = None, precompute: bool = False) -> None:
    resolved_user = normalize_user_id(user_id or get_current_user_id()) if (user_id or get_current_user_id()) else None
    final_tags = set(str(tag) for tag in (tags or ()))
    if path:
        final_tags.update(tags_for_path(path, user_id=resolved_user))
    if not final_tags:
        final_tags.add("money_rows")
    invalidate_tags(final_tags, user_id=resolved_user)
    if precompute and resolved_user:
        try:
            precompute_after_write(final_tags, user_id=resolved_user)
        except Exception:
            pass
    elif resolved_user and os.environ.get("MONEY_MANAGER_AUTO_PRECOMPUTE_AFTER_WRITE", "").strip() == "1":
        # Rebuilding dashboard/account summaries after every write made the UI
        # feel blocked on slower disks and encrypted data folders.  The app now
        # invalidates exactly what changed and recomputes lazily; opt back in by
        # setting MONEY_MANAGER_AUTO_PRECOMPUTE_AFTER_WRITE=1.
        schedule_cache_refresh(delay=5.0, user_id=resolved_user)


def notify_path_changed(path: str, *, user_id: str | None = None) -> None:
    notify_data_changed(user_id=user_id, path=path)


def schedule_cache_refresh(delay: float = WARMUP_DEBOUNCE_SECONDS, *, user_id: str | None = None) -> None:
    resolved_user = normalize_user_id(user_id or get_current_user_id()) if (user_id or get_current_user_id()) else None
    if not resolved_user:
        return

    def _run() -> None:
        with using_user(resolved_user):
            try:
                precompute_user_dashboard(user_id=resolved_user)
            except Exception:
                pass

    with _LOCK:
        old_timer = _BACKGROUND_TIMERS.get(resolved_user)
        if old_timer is not None:
            try:
                old_timer.cancel()
            except Exception:
                pass
        timer = threading.Timer(delay, _run)
        timer.daemon = True
        _BACKGROUND_TIMERS[resolved_user] = timer
        timer.start()


def warm_app_cache_async() -> None:
    user_id = get_current_user_id()
    if not user_id:
        return
    with _LOCK:
        if user_id in _STARTUP_WARMED:
            return
        _STARTUP_WARMED.add(user_id)
    try:
        warm_cache_on_login(user_id)
    except Exception:
        pass


def warm_default_calculations(*, user_id: str | None = None) -> None:
    resolved_user = normalize_user_id(user_id or get_current_user_id()) if (user_id or get_current_user_id()) else None
    if not resolved_user:
        return
    with using_user(resolved_user):
        try:
            precompute_user_dashboard(user_id=resolved_user)
        except Exception:
            pass


def cache_status() -> dict[str, Any]:
    status = _cache_status()
    try:
        status["turbo_memory_cache"] = fast_memory_cache.stats()
    except Exception:
        pass
    try:
        from money_manager.repositories.csv_files import row_cache_stats

        status["csv_row_cache"] = row_cache_stats()
    except Exception:
        pass
    try:
        from money_manager.cache import json_read_cache

        status["json_object_cache"] = json_read_cache.stats()
    except Exception:
        pass
    try:
        from money_manager.performance.navigation_accelerator import stats as navigation_cache_stats

        status["adaptive_page_cache"] = navigation_cache_stats()
    except Exception:
        pass
    return status
