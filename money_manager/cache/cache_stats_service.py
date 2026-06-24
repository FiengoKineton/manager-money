from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from money_manager.config.install_paths import GLOBAL_CACHE_DIR
from money_manager.config.user_paths import get_current_user_id, normalize_user_id

STAT_KEYS = ("hits", "misses", "recomputes", "invalidations", "stale_skips", "errors")
_STATS_LOCK = threading.RLock()
_PENDING: dict[str, dict[str, Any]] = {}
_LAST_FLUSH: dict[str, float] = {}
_FLUSH_INTERVAL_SECONDS = float(os.environ.get("MONEY_MANAGER_CACHE_STATS_FLUSH_SECONDS", "15") or 15)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_user(user_id: str | None = None) -> str:
    return normalize_user_id(user_id or get_current_user_id()) if (user_id or get_current_user_id()) else "anonymous"


def user_cache_root(user_id: str | None = None) -> Path:
    resolved = _safe_user(user_id)
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
    safe_id = _safe_user(user_id)
    path = stats_path(safe_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        payload = {}
    stats = default_stats()
    if isinstance(payload, dict):
        stats.update(payload)
    with _STATS_LOCK:
        pending = dict(_PENDING.get(safe_id) or {})
    _apply_pending(stats, pending)
    for key in STAT_KEYS:
        try:
            stats[key] = int(stats.get(key, 0) or 0)
        except Exception:
            stats[key] = 0
    return stats


def save_stats(stats: dict[str, Any], user_id: str | None = None) -> None:
    safe_id = _safe_user(user_id)
    payload = dict(default_stats())
    payload.update(stats or {})
    payload["updated_at"] = utc_now()
    path = stats_path(safe_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", delete=False, dir=str(path.parent), prefix=".cache_stats.", suffix=".tmp", encoding="utf-8") as tmp:
        json.dump(payload, tmp, indent=2, ensure_ascii=False)
        temp_name = tmp.name
    Path(temp_name).replace(path)
    with _STATS_LOCK:
        _LAST_FLUSH[safe_id] = time.time()


def record(event: str, *, user_id: str | None = None, compute_time: float | None = None, error: str = "") -> None:
    try:
        safe_id = _safe_user(user_id)
        with _STATS_LOCK:
            pending = _PENDING.setdefault(safe_id, {})
            if event in STAT_KEYS:
                pending[event] = int(pending.get(event, 0) or 0) + 1
            if compute_time is not None:
                pending["total_compute_time_seconds"] = float(pending.get("total_compute_time_seconds", 0.0) or 0.0) + float(compute_time)
                pending["compute_samples"] = int(pending.get("compute_samples", 0) or 0) + 1
            if error:
                pending["last_error"] = str(error)[:500]
            should_flush = bool(error) or (time.time() - float(_LAST_FLUSH.get(safe_id, 0.0) or 0.0) >= _FLUSH_INTERVAL_SECONDS)
        if should_flush:
            flush_stats(safe_id)
    except Exception:
        pass


def flush_stats(user_id: str | None = None) -> None:
    safe_id = _safe_user(user_id)
    with _STATS_LOCK:
        pending = _PENDING.pop(safe_id, {})
    if not pending:
        return
    stats = _load_stats_file(safe_id)
    _apply_pending(stats, pending)
    save_stats(stats, safe_id)


def record_rebuild(user_id: str | None = None) -> None:
    safe_id = _safe_user(user_id)
    flush_stats(safe_id)
    stats = load_stats(safe_id)
    stats["last_rebuild_at"] = utc_now()
    save_stats(stats, safe_id)


def record_clear(user_id: str | None = None) -> None:
    safe_id = _safe_user(user_id)
    flush_stats(safe_id)
    stats = load_stats(safe_id)
    stats["last_clear_at"] = utc_now()
    save_stats(stats, safe_id)


def _load_stats_file(user_id: str) -> dict[str, Any]:
    path = stats_path(user_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        payload = {}
    stats = default_stats()
    if isinstance(payload, dict):
        stats.update(payload)
    return stats


def _apply_pending(stats: dict[str, Any], pending: dict[str, Any]) -> None:
    for key in STAT_KEYS:
        if key in pending:
            stats[key] = int(stats.get(key, 0) or 0) + int(pending.get(key, 0) or 0)
    if "total_compute_time_seconds" in pending:
        stats["total_compute_time_seconds"] = float(stats.get("total_compute_time_seconds", 0.0) or 0.0) + float(pending.get("total_compute_time_seconds", 0.0) or 0.0)
    if "compute_samples" in pending:
        stats["compute_samples"] = int(stats.get("compute_samples", 0) or 0) + int(pending.get("compute_samples", 0) or 0)
    if pending.get("last_error"):
        stats["last_error"] = str(pending.get("last_error"))[:500]
    stats["updated_at"] = utc_now()
