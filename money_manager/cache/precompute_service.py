from __future__ import annotations

import threading
from typing import Iterable

from money_manager.cache.cache_invalidation import clear_user_cache, invalidate_tags
from money_manager.cache.cache_manager import rebuild_cache_entry
from money_manager.cache.cache_registry import get_cache_definition
from money_manager.cache.cache_stats_service import record_rebuild
from money_manager.config.user_paths import get_current_user_id, normalize_user_id, using_user

_SMALL_LOGIN_CACHES = ("profile_context", "preferences_context", "navigation_context")
_DASHBOARD_CACHES = ("quick_overview",)
_ACCOUNT_CACHES = ("account_balances",)


def precompute_user_dashboard(user_id: str | None = None) -> dict:
    return _precompute(_DASHBOARD_CACHES, user_id=user_id)


def precompute_account_summaries(user_id: str | None = None) -> dict:
    return _precompute(_ACCOUNT_CACHES, user_id=user_id)


def precompute_monthly_summaries(user_id: str | None = None, year: int | None = None) -> dict:
    return _precompute(("monthly_summary", "category_summary", "payment_method_breakdown", "account_breakdown"), user_id=user_id, params={"year": year} if year else {})


def precompute_after_write(tags: Iterable[str], user_id: str | None = None) -> dict:
    safe_id = _resolve(user_id)
    invalidate_tags(tags, user_id=safe_id)
    # Keep post-write refresh deliberately light. Fingerprints still protect
    # correctness if nothing is precomputed.
    return _precompute(("quick_overview",), user_id=safe_id)


def warm_cache_on_login(user_id: str | None = None) -> None:
    safe_id = _resolve(user_id)

    def _run() -> None:
        with using_user(safe_id):
            _precompute(_SMALL_LOGIN_CACHES, user_id=safe_id)

    thread = threading.Thread(target=_run, name=f"money-manager-cache-login-warm-{safe_id}", daemon=True)
    thread.start()


def clear_user_cache_now(user_id: str | None = None) -> int:
    return clear_user_cache(user_id=user_id)


def rebuild_user_cache(user_id: str | None = None) -> dict:
    safe_id = _resolve(user_id)
    removed = clear_user_cache(user_id=safe_id)
    result = _precompute((*_SMALL_LOGIN_CACHES, *_DASHBOARD_CACHES, *_ACCOUNT_CACHES), user_id=safe_id)
    result["removed"] = removed
    record_rebuild(safe_id)
    return result


def _precompute(names: Iterable[str], *, user_id: str | None = None, params: dict | None = None) -> dict:
    safe_id = _resolve(user_id)
    report = {"user_id": safe_id, "ok": [], "skipped": [], "errors": {}}
    with using_user(safe_id):
        for name in names:
            definition = get_cache_definition(name)
            if not definition.rebuild_import_path:
                report["skipped"].append(name)
                continue
            try:
                rebuild_cache_entry(name, user_id=safe_id, params=params or {})
                report["ok"].append(name)
            except Exception as exc:
                report["errors"][name] = str(exc)[:300]
    return report


def _resolve(user_id: str | None = None) -> str:
    resolved = user_id or get_current_user_id()
    if not resolved:
        raise RuntimeError("No user available for cache precompute.")
    return normalize_user_id(resolved)
