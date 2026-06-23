from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from money_manager.config.user_defaults import USER_CONFIG_DEFAULTS, default_for
from money_manager.config.user_paths import user_data_path
from money_manager.security.secure_storage import read_json_secure, write_json_secure

CONFIG_FILENAMES = frozenset(USER_CONFIG_DEFAULTS.keys())


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
    raw = read_json_secure(path, None, user_id=user_id)
    merged = deep_merge_defaults(default, raw)
    if not isinstance(merged, dict):
        merged = default
    if repair and (raw != merged or not path.exists()):
        write_json_secure(path, merged, user_id=user_id)
    return merged


def save_user_config(filename: str, payload: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    default = default_for(filename)
    merged = deep_merge_defaults(default, dict(payload or {}))
    if not isinstance(merged, dict):
        merged = default
    write_json_secure(config_path(filename, user_id=user_id), merged, user_id=user_id)
    return merged


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
