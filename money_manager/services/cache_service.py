"""Compatibility facade for the professional cache package.

Old imports keep working, but the implementation now lives in
``money_manager.cache`` and stores disposable per-user cache under the external
MoneyManagerData/cache folder.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from typing import Any

from money_manager.cache.cache_invalidation import invalidate_all, invalidate_tags
from money_manager.cache.cache_manager import cache_status as _cache_status, data_fingerprint as _data_fingerprint, get_or_compute
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
    return get_or_compute(
        key,
        builder,
        params={"legacy_key": key, "extra": extra_fingerprint or {}},
        extra_fingerprint=extra_fingerprint,
        allow_stale_on_error=allow_stale_on_error,
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
    elif resolved_user:
        schedule_cache_refresh(user_id=resolved_user)


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
    return _cache_status()
