from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, url_for

from money_manager.cache.cache_invalidation import cleanup_stale_entries, clear_user_cache
from money_manager.cache.cache_stats_service import record_clear
from money_manager.cache.cache_store import cache_inventory
from money_manager.cache.precompute_service import rebuild_user_cache
from money_manager.config.user_paths import get_current_user_id

bp = Blueprint("settings_cache", __name__, url_prefix="/settings")


def _template_context(*, action_result=None, error=None) -> dict:
    user_id = get_current_user_id()
    try:
        from money_manager.performance.navigation_accelerator import stats as adaptive_page_cache_stats

        page_cache = adaptive_page_cache_stats(user_id=user_id)
    except Exception:
        page_cache = {
            "enabled": False,
            "entry_count": 0,
            "total_bytes": 0,
            "stats": {},
            "entries": [],
            "usage": {},
        }
    return {
        "cache": cache_inventory(user_id=user_id),
        "adaptive_page_cache": page_cache,
        "action_result": action_result,
        "error": error,
    }


@bp.get("/cache")
def cache_page():
    return render_template("settings/cache.html", **_template_context())


@bp.post("/cache/clear")
def clear_cache_route():
    error = None
    action_result = None
    try:
        removed = clear_user_cache(user_id=get_current_user_id())
        record_clear(get_current_user_id())
        action_result = {"message": "cache_cleared", "removed": removed}
    except Exception as exc:
        error = str(exc)
    return render_template("settings/cache.html", **_template_context(action_result=action_result, error=error))


@bp.post("/cache/rebuild")
def rebuild_cache_route():
    error = None
    action_result = None
    try:
        action_result = rebuild_user_cache(user_id=get_current_user_id())
        action_result["message"] = "cache_rebuilt"
    except Exception as exc:
        error = str(exc)
    return render_template("settings/cache.html", **_template_context(action_result=action_result, error=error))


@bp.post("/cache/cleanup-stale")
def cleanup_stale_route():
    error = None
    action_result = None
    try:
        removed = cleanup_stale_entries(user_id=get_current_user_id())
        action_result = {"message": "stale_removed", "removed": removed}
    except Exception as exc:
        error = str(exc)
    return render_template("settings/cache.html", **_template_context(action_result=action_result, error=error))
