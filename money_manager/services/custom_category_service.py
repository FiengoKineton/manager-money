from __future__ import annotations

from typing import Any, Mapping

import money_manager.config.categories as app_categories
from money_manager.config.user_defaults import DEFAULT_CATEGORIES
from money_manager.services._user_config import load_user_config, save_user_config

CATEGORIES_FILE = "categories.json"


def load_categories_config(user_id: str | None = None) -> dict[str, Any]:
    return _normalize_categories(load_user_config(CATEGORIES_FILE, user_id=user_id))


def save_categories_config(config: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    payload = _normalize_categories(config)
    return save_user_config(CATEGORIES_FILE, payload, user_id=user_id)


def sort_categories(values: Any) -> list[str]:
    cleaned = [_clean_category(value) for value in values or []]
    cleaned = [value for value in cleaned if value]
    return sorted(cleaned, key=lambda value: (value.casefold(), value))


def effective_categories_for(transaction_type: str, user_id: str | None = None) -> list[str]:
    transaction_type = _normalize_transaction_type(transaction_type)
    config = load_categories_config(user_id=user_id)
    section = config[transaction_type]
    hidden = {_case_key(item) for item in section.get("hidden", [])}

    result: list[str] = []
    seen: set[str] = set()

    for category in [*app_categories.CATEGORY_OPTIONS.get(transaction_type, []), *section.get("custom", [])]:
        clean = _clean_category(category)
        key = _case_key(clean)

        if not clean or key in hidden or key in seen:
            continue

        result.append(clean)
        seen.add(key)

    return sort_categories(result)


def effective_categories_by_type(user_id: str | None = None) -> dict[str, list[str]]:
    return {transaction_type: effective_categories_for(transaction_type, user_id=user_id) for transaction_type in app_categories.TRANSACTION_TYPES}


def default_category_for(transaction_type: str, user_id: str | None = None) -> str:
    transaction_type = _normalize_transaction_type(transaction_type)
    config = load_categories_config(user_id=user_id)
    options = effective_categories_for(transaction_type, user_id=user_id)
    configured_default = _clean_category(config[transaction_type].get("default"))
    if configured_default in options:
        return configured_default
    app_default = app_categories.DEFAULT_CATEGORY_BY_TYPE.get(transaction_type, "")
    if app_default in options:
        return app_default
    return options[0] if options else ""


def add_custom_category(transaction_type: str, name: str, user_id: str | None = None) -> dict[str, Any]:
    transaction_type = _normalize_transaction_type(transaction_type)
    category = _clean_category(name)
    if not category:
        raise ValueError("Category name is required.")
    config = load_categories_config(user_id=user_id)
    section = config[transaction_type]
    existing = {_case_key(item) for item in [*app_categories.CATEGORY_OPTIONS.get(transaction_type, []), *section.get("custom", [])]}
    if _case_key(category) not in existing:
        section["custom"].append(category)
        section["custom"] = sort_categories(section.get("custom", []))
    section["hidden"] = [item for item in section.get("hidden", []) if _case_key(item) != _case_key(category)]
    return save_categories_config(config, user_id=user_id)


def hide_category(transaction_type: str, name: str, user_id: str | None = None) -> dict[str, Any]:
    transaction_type = _normalize_transaction_type(transaction_type)
    category = _clean_category(name)
    if not category:
        raise ValueError("Category name is required.")
    config = load_categories_config(user_id=user_id)
    section = config[transaction_type]
    if _case_key(category) not in {_case_key(item) for item in section.get("hidden", [])}:
        section["hidden"].append(category)
    return save_categories_config(config, user_id=user_id)


def restore_category(transaction_type: str, name: str, user_id: str | None = None) -> dict[str, Any]:
    transaction_type = _normalize_transaction_type(transaction_type)
    category = _clean_category(name)
    config = load_categories_config(user_id=user_id)
    section = config[transaction_type]
    section["hidden"] = [item for item in section.get("hidden", []) if _case_key(item) != _case_key(category)]
    return save_categories_config(config, user_id=user_id)


def set_default_category(transaction_type: str, name: str, user_id: str | None = None) -> dict[str, Any]:
    transaction_type = _normalize_transaction_type(transaction_type)
    category = _clean_category(name)
    if category not in effective_categories_for(transaction_type, user_id=user_id):
        raise ValueError("Default category must be an active category.")
    config = load_categories_config(user_id=user_id)
    config[transaction_type]["default"] = category
    return save_categories_config(config, user_id=user_id)


def ensure_categories_config(user_id: str | None = None) -> dict[str, Any]:
    return load_categories_config(user_id=user_id)


def _normalize_categories(config: Mapping[str, Any]) -> dict[str, Any]:
    clean = dict(DEFAULT_CATEGORIES)
    incoming = dict(config or {})
    clean["schema_version"] = incoming.get("schema_version") or DEFAULT_CATEGORIES["schema_version"]
    for transaction_type in app_categories.TRANSACTION_TYPES:
        section = incoming.get(transaction_type, {}) if isinstance(incoming.get(transaction_type, {}), dict) else {}
        default_section = DEFAULT_CATEGORIES[transaction_type]
        clean[transaction_type] = {
            "custom": sort_categories(_unique_categories(section.get("custom", default_section["custom"]))),
            "hidden": sort_categories(_unique_categories(section.get("hidden", default_section["hidden"]))),
            "default": _clean_category(section.get("default", default_section["default"])),
        }
    for key, value in incoming.items():
        if key not in clean:
            clean[key] = value
    return clean


def _normalize_transaction_type(transaction_type: str) -> str:
    value = str(transaction_type or "").strip().lower()
    return value if value in app_categories.TRANSACTION_TYPES else "expense"


def _clean_category(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _case_key(value: Any) -> str:
    return _clean_category(value).casefold()


def _unique_categories(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = _clean_category(value)
        key = _case_key(clean)
        if clean and key not in seen:
            result.append(clean)
            seen.add(key)
    return result
