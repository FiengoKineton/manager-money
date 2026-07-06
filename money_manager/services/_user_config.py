import os
from __future__ import annotations

from copy import deepcopy
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from money_manager.config.user_defaults import USER_CONFIG_DEFAULTS, default_for
from money_manager.config.user_paths import normalize_user_id, user_data_path
from money_manager.security.secure_storage import read_json_secure, write_json_secure

CONFIG_FILENAMES = frozenset(USER_CONFIG_DEFAULTS.keys())

_CONFIG_CACHE_LOCK = threading.RLock()
_CONFIG_CACHE: dict[tuple[str, str, str, int, int, bool], dict[str, Any]] = {}
_CONFIG_CACHE_MAX_ENTRIES = 128


def _stat_signature(path: Path) -> tuple[int, int]:
    try:
        stat = path.stat()
        return int(stat.st_mtime_ns), int(stat.st_size)
    except OSError:
        return 0, 0


def _cache_user_id(user_id: str | None) -> str:
    try:
        return normalize_user_id(user_id) if user_id else ""
    except Exception:
        return str(user_id or "")


def _get_cached_config(key: tuple[str, str, str, int, int, bool]) -> dict[str, Any] | None:
    with _CONFIG_CACHE_LOCK:
        value = _CONFIG_CACHE.get(key)
        if value is None:
            return None
        return deepcopy(value)


def _set_cached_config(key: tuple[str, str, str, int, int, bool], value: Mapping[str, Any]) -> None:
    with _CONFIG_CACHE_LOCK:
        _CONFIG_CACHE[key] = deepcopy(dict(value or {}))
        if len(_CONFIG_CACHE) > _CONFIG_CACHE_MAX_ENTRIES:
            for old_key in list(_CONFIG_CACHE.keys())[: max(1, _CONFIG_CACHE_MAX_ENTRIES // 4)]:
                _CONFIG_CACHE.pop(old_key, None)


def _invalidate_config_cache(filename: str | None = None, user_id: str | None = None) -> None:
    safe_id = _cache_user_id(user_id)
    with _CONFIG_CACHE_LOCK:
        for key in list(_CONFIG_CACHE.keys()):
            key_user, key_filename, _key_path, *_rest = key
            if safe_id and key_user != safe_id:
                continue
            if filename and key_filename != filename:
                continue
            _CONFIG_CACHE.pop(key, None)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def config_path(filename: str, user_id: str | None = None) -> Path:
    if filename not in CONFIG_FILENAMES:
        raise ValueError(f"Unsupported user config file: {filename}")
    return Path(user_data_path(filename, user_id=user_id))


def deep_merge_defaults(default: Any, existing: Any) -> Any:
    """Merge defaults into existing data while preserving valid existing values."""
    if isinstance(default, dict):
        if not isinstance(existing, dict):
            return deepcopy(default)
        merged: dict[str, Any] = {}
        for key, default_value in default.items():
            if key in existing:
                if key == "schema_version":
                    merged[key] = existing.get(key) or deepcopy(default_value)
                else:
                    merged[key] = deep_merge_defaults(default_value, existing.get(key))
            else:
                merged[key] = deepcopy(default_value)
        for key, value in existing.items():
            if key not in merged:
                merged[key] = deepcopy(value)
        return merged
    if isinstance(default, list):
        return deepcopy(existing) if isinstance(existing, list) else deepcopy(default)
    return deepcopy(existing) if existing is not None else deepcopy(default)


def load_user_config(filename: str, user_id: str | None = None, *, repair: bool = True) -> dict[str, Any]:
    default = default_for(filename)
    try:
        path = config_path(filename, user_id=user_id)
    except RuntimeError:
        return default

    mtime_ns, size = _stat_signature(path)
    cache_key = (_cache_user_id(user_id), filename, str(path), mtime_ns, size, bool(repair))
    cached = _get_cached_config(cache_key)
    if cached is not None:
        return cached

    raw = read_json_secure(path, None, user_id=user_id)
    merged = deep_merge_defaults(default, raw)
    if not isinstance(merged, dict):
        merged = default

    repair_on_read = os.environ.get("MONEY_MANAGER_REPAIR_CONFIG_ON_READ", "0").strip() == "1"

    if repair and repair_on_read and (raw != merged or not path.exists()):
        write_json_secure(path, merged, user_id=user_id)
        mtime_ns, size = _stat_signature(path)
        cache_key = (_cache_user_id(user_id), filename, str(path), mtime_ns, size, bool(repair))
        
    _set_cached_config(cache_key, merged)
    return deepcopy(merged)


def save_user_config(filename: str, payload: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    default = default_for(filename)
    merged = deep_merge_defaults(default, dict(payload or {}))
    if not isinstance(merged, dict):
        merged = default
    write_json_secure(config_path(filename, user_id=user_id), merged, user_id=user_id)
    _invalidate_config_cache(filename, user_id=user_id)
    try:
        path = config_path(filename, user_id=user_id)
        mtime_ns, size = _stat_signature(path)
        _set_cached_config((_cache_user_id(user_id), filename, str(path), mtime_ns, size, True), merged)
    except Exception:
        pass
    return deepcopy(merged)


def safe_update_fields(
    current: Mapping[str, Any],
    updates: Mapping[str, Any],
    *,
    allowed_fields: Iterable[str] | None = None,
    allow_unknown: bool = False,
) -> dict[str, Any]:
    """Return a copy of current with only safe scalar/list/dict JSON fields updated."""
    result = deepcopy(dict(current or {}))
    allowed = set(allowed_fields or [])
    for key, value in dict(updates or {}).items():
        key_text = str(key or "").strip()
        if not key_text or key_text.startswith("_"):
            continue
        if allowed and key_text not in allowed and not allow_unknown:
            continue
        if isinstance(value, (str, int, float, bool, list, dict)) or value is None:
            result[key_text] = value
    return result
