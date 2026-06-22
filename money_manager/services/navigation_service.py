from __future__ import annotations

from typing import Any, Mapping

from money_manager.config.user_defaults import DEFAULT_NAVIGATION
from money_manager.services._user_config import load_user_config, save_user_config

NAVIGATION_FILE = "navigation.json"


def load_navigation_config(user_id: str | None = None) -> dict[str, Any]:
    return _normalize_navigation(load_user_config(NAVIGATION_FILE, user_id=user_id))


def save_navigation_config(config: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    return save_user_config(NAVIGATION_FILE, _normalize_navigation(config), user_id=user_id)


def hidden_pages(user_id: str | None = None) -> list[str]:
    return load_navigation_config(user_id=user_id).get("hidden_pages", [])


def is_page_hidden(page_key: str, user_id: str | None = None) -> bool:
    return _safe_key(page_key) in set(hidden_pages(user_id=user_id))


def hide_page(page_key: str, user_id: str | None = None) -> dict[str, Any]:
    key = _safe_key(page_key)
    if not key:
        raise ValueError("Page key is required.")
    config = load_navigation_config(user_id=user_id)
    if key not in config["hidden_pages"]:
        config["hidden_pages"].append(key)
    return save_navigation_config(config, user_id=user_id)


def restore_page(page_key: str, user_id: str | None = None) -> dict[str, Any]:
    key = _safe_key(page_key)
    config = load_navigation_config(user_id=user_id)
    config["hidden_pages"] = [item for item in config["hidden_pages"] if item != key]
    return save_navigation_config(config, user_id=user_id)


def set_custom_order(order: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    config = load_navigation_config(user_id=user_id)
    config["custom_order"] = _normalize_order_map(order)
    return save_navigation_config(config, user_id=user_id)


def set_group_order(order: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    config = load_navigation_config(user_id=user_id)
    config["group_order"] = _normalize_order_map(order)
    return save_navigation_config(config, user_id=user_id)


def collapse_group(group_key: str, user_id: str | None = None) -> dict[str, Any]:
    key = _safe_key(group_key)
    if not key:
        raise ValueError("Group key is required.")
    config = load_navigation_config(user_id=user_id)
    if key not in config["collapsed_groups"]:
        config["collapsed_groups"].append(key)
    return save_navigation_config(config, user_id=user_id)


def expand_group(group_key: str, user_id: str | None = None) -> dict[str, Any]:
    key = _safe_key(group_key)
    config = load_navigation_config(user_id=user_id)
    config["collapsed_groups"] = [item for item in config["collapsed_groups"] if item != key]
    return save_navigation_config(config, user_id=user_id)


def ensure_navigation_config(user_id: str | None = None) -> dict[str, Any]:
    return load_navigation_config(user_id=user_id)


def _normalize_navigation(config: Mapping[str, Any]) -> dict[str, Any]:
    incoming = dict(config or {})
    clean = dict(DEFAULT_NAVIGATION)
    clean["schema_version"] = incoming.get("schema_version") or DEFAULT_NAVIGATION["schema_version"]
    clean["hidden_pages"] = _unique_keys(incoming.get("hidden_pages", []))
    clean["collapsed_groups"] = _unique_keys(incoming.get("collapsed_groups", []))
    clean["custom_order"] = _normalize_order_map(incoming.get("custom_order", {}))
    clean["group_order"] = _normalize_order_map(incoming.get("group_order", {}))
    for key, value in incoming.items():
        if key not in clean:
            clean[key] = value
    return clean


def _normalize_order_map(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, int] = {}
    for key, order in value.items():
        safe = _safe_key(key)
        if not safe:
            continue
        try:
            result[safe] = int(order)
        except (TypeError, ValueError):
            continue
    return result


def _unique_keys(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = _safe_key(value)
        if key and key not in seen:
            result.append(key)
            seen.add(key)
    return result


def _safe_key(value: Any) -> str:
    text = str(value or "").strip().lower().replace(" ", "_")
    if ".." in text or "/" in text or "\\" in text:
        return ""
    return "".join(char for char in text if char.isalnum() or char in {"_", "-", ".", ":"})[:120]
