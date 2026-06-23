from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from money_manager.config.install_paths import GLOBAL_CACHE_DIR
from money_manager.config.user_paths import get_current_user_id, normalize_user_id

STAT_KEYS = ("hits", "misses", "recomputes", "invalidations", "stale_skips", "errors")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def user_cache_root(user_id: str | None = None) -> Path:
    resolved = normalize_user_id(user_id or get_current_user_id()) if (user_id or get_current_user_id()) else "anonymous"
    path = GLOBAL_CACHE_DIR / "users" / resolved
    path.mkdir(parents=True, exist_ok=True)
    return path


def stats_path(user_id: str | None = None) -> Path:
    return user_cache_root(user_id) / "cache_stats.json"


def default_stats() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "hits": 0,
        "misses": 0,
        "recomputes": 0,
        "invalidations": 0,
        "stale_skips": 0,
        "errors": 0,
        "total_compute_time_seconds": 0.0,
        "compute_samples": 0,
        "last_rebuild_at": "",
        "last_clear_at": "",
        "last_error": "",
    }


def load_stats(user_id: str | None = None) -> dict[str, Any]:
    path = stats_path(user_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        payload = {}
    stats = default_stats()
    if isinstance(payload, dict):
        stats.update(payload)
    for key in STAT_KEYS:
        try:
            stats[key] = int(stats.get(key, 0) or 0)
        except Exception:
            stats[key] = 0
    return stats


def save_stats(stats: dict[str, Any], user_id: str | None = None) -> None:
    payload = dict(default_stats())
    payload.update(stats or {})
    payload["updated_at"] = utc_now()
    path = stats_path(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", delete=False, dir=str(path.parent), prefix=".cache_stats.", suffix=".tmp", encoding="utf-8") as tmp:
        json.dump(payload, tmp, indent=2, ensure_ascii=False)
        temp_name = tmp.name
    Path(temp_name).replace(path)


def record(event: str, *, user_id: str | None = None, compute_time: float | None = None, error: str = "") -> None:
    try:
        stats = load_stats(user_id)
        if event in STAT_KEYS:
            stats[event] = int(stats.get(event, 0) or 0) + 1
        if compute_time is not None:
            stats["total_compute_time_seconds"] = float(stats.get("total_compute_time_seconds", 0.0) or 0.0) + float(compute_time)
            stats["compute_samples"] = int(stats.get("compute_samples", 0) or 0) + 1
        if error:
            stats["last_error"] = str(error)[:500]
        save_stats(stats, user_id)
    except Exception:
        pass


def record_rebuild(user_id: str | None = None) -> None:
    stats = load_stats(user_id)
    stats["last_rebuild_at"] = utc_now()
    save_stats(stats, user_id)


def record_clear(user_id: str | None = None) -> None:
    stats = load_stats(user_id)
    stats["last_clear_at"] = utc_now()
    save_stats(stats, user_id)
