from __future__ import annotations

from typing import Iterable

from money_manager.cache import process_cache, request_cache, runtime_epoch
from money_manager.cache.cache_stats_service import record
from money_manager.cache.cache_store import cleanup_stale_entries as _cleanup_stale_entries, clear_user_cache as _clear_user_cache, mark_stale
from money_manager.cache.source_fingerprint_service import TAG_ALIASES
from money_manager.config.user_paths import get_current_user_id, normalize_user_id


def expand_tags(tags: Iterable[str] | None) -> set[str]:
    expanded: set[str] = set()
    for tag in tags or ():
        text = str(tag or "").strip()
        if not text:
            continue
        expanded.add(text)
        expanded.update(TAG_ALIASES.get(text, ()))
    return expanded


def _clear_turbo_cache(user_id: str | None = None, tags: Iterable[str] | None = None) -> None:
    try:
        from money_manager.performance import fast_memory_cache

        fast_memory_cache.clear(user_id=user_id, tags=tags)
    except Exception:
        pass


def _note_turbo_data_changed(user_id: str | None = None, tags: Iterable[str] | None = None) -> None:
    try:
        from money_manager.performance import turbo_version_service

        turbo_version_service.note_data_changed(user_id=user_id, tags=tags)
    except Exception:
        pass


def _invalidate_rendered_pages(user_id: str | None = None, tags: Iterable[str] | None = None) -> None:
    try:
        from money_manager.performance.navigation_accelerator import invalidate_pages

        invalidate_pages(user_id=user_id, tags=tags)
    except Exception:
        pass


def invalidate_tags(tags: Iterable[str], user_id: str | None = None) -> int:
    safe_id = _resolve_optional_user(user_id)
    expanded = expand_tags(tags)
    if not safe_id:
        request_cache.clear_user()
        process_cache.clear()
        return 0
    runtime_epoch.bump(safe_id, expanded)
    _note_turbo_data_changed(user_id=safe_id, tags=expanded)
    count = mark_stale(tags=expanded, user_id=safe_id, reason="tag_invalidation")
    request_cache.clear_user(safe_id)
    process_cache.clear(user_id=safe_id, tags=expanded)
    _clear_turbo_cache(user_id=safe_id, tags=expanded)
    _invalidate_rendered_pages(user_id=safe_id, tags=expanded)
    try:
        from money_manager.cache.source_fingerprint_service import clear_fingerprint_caches

        clear_fingerprint_caches(user_id=safe_id)
    except Exception:
        pass
    record("invalidations", user_id=safe_id)
    return count


def invalidate_key(key: str, user_id: str | None = None) -> int:
    safe_id = _resolve_optional_user(user_id)
    if not safe_id:
        request_cache.clear_user()
        process_cache.clear()
        return 0
    runtime_epoch.bump(safe_id, ())
    _note_turbo_data_changed(user_id=safe_id, tags=())
    count = mark_stale(entry_ids=[key], user_id=safe_id, reason="key_invalidation")
    request_cache.clear_user(safe_id)
    process_cache.clear(user_id=safe_id)
    _clear_turbo_cache(user_id=safe_id)
    _invalidate_rendered_pages(user_id=safe_id, tags=())
    try:
        from money_manager.cache.source_fingerprint_service import clear_fingerprint_caches

        clear_fingerprint_caches(user_id=safe_id)
    except Exception:
        pass
    record("invalidations", user_id=safe_id)
    return count


def invalidate_user_cache(user_id: str | None = None) -> int:
    safe_id = _resolve_optional_user(user_id)
    if not safe_id:
        request_cache.clear_user()
        process_cache.clear()
        return 0
    runtime_epoch.bump(safe_id, ())
    _note_turbo_data_changed(user_id=safe_id, tags=())
    count = mark_stale(user_id=safe_id, reason="user_invalidation")
    request_cache.clear_user(safe_id)
    process_cache.clear(user_id=safe_id)
    _clear_turbo_cache(user_id=safe_id)
    _invalidate_rendered_pages(user_id=safe_id, tags=())
    try:
        from money_manager.cache.source_fingerprint_service import clear_fingerprint_caches

        clear_fingerprint_caches(user_id=safe_id)
    except Exception:
        pass
    record("invalidations", user_id=safe_id)
    return count


def invalidate_all() -> int:
    # In the web app we only know the current user's safe context. Update tools
    # can clear folders directly if they need a global wipe.
    return invalidate_user_cache()


def mark_stale_by_tags(tags: Iterable[str], user_id: str | None = None) -> int:
    return invalidate_tags(tags, user_id=user_id)


def cleanup_stale_entries(user_id: str | None = None) -> int:
    safe_id = _resolve_optional_user(user_id)
    if not safe_id:
        return 0
    return _cleanup_stale_entries(user_id=safe_id)


def clear_user_cache(user_id: str | None = None) -> int:
    safe_id = _resolve_optional_user(user_id)
    if not safe_id:
        request_cache.clear_user()
        process_cache.clear()
        return 0
    runtime_epoch.bump(safe_id, ())
    _note_turbo_data_changed(user_id=safe_id, tags=())
    count = _clear_user_cache(user_id=safe_id)
    request_cache.clear_user(safe_id)
    process_cache.clear(user_id=safe_id)
    _clear_turbo_cache(user_id=safe_id)
    _invalidate_rendered_pages(user_id=safe_id, tags=())
    try:
        from money_manager.cache.source_fingerprint_service import clear_fingerprint_caches

        clear_fingerprint_caches(user_id=safe_id)
    except Exception:
        pass
    record("invalidations", user_id=safe_id)
    return count


def _resolve_optional_user(user_id: str | None = None) -> str | None:
    resolved = user_id or get_current_user_id()
    return normalize_user_id(resolved) if resolved else None
