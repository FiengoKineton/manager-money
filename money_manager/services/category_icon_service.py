from __future__ import annotations

from typing import Any, Mapping

from money_manager.config import categories as app_categories
from money_manager.services._user_config import load_user_config, save_user_config

CATEGORY_ICONS_FILE = "category_icons.json"
DEFAULT_ICON = "💸"

# Local, offline icon database. Using emoji keeps the app fast, portable and
# independent from external icon CDNs/web scraping.
DEFAULT_CATEGORY_ICONS: dict[str, str] = {
    # Expense defaults
    "food": "🍔",
    "groceries": "🛒",
    "restaurants": "🍽️",
    "transport": "🚆",
    "housing": "🏠",
    "utilities": "💡",
    "health": "⚕️",
    "personal care": "🧴",
    "shopping": "🛍️",
    "subscriptions": "🔁",
    "travel": "✈️",
    "gifts": "🎁",
    "charity": "🤲",
    "savings": "🐷",
    "debt": "⚠️",
    "credit cards": "💳",
    "payable": "🧾",
    "account cleanup": "🧹",
    "other": "💸",
    # Income defaults
    "salary": "💼",
    "scholarship": "🎓",
    "refund": "↩️",
    "family": "👪",
    "friends": "🧑‍🤝‍🧑",
    "other income": "💰",
    # Investment defaults
    "deposit": "🏦",
    "withdrawal": "🏧",
    "buy": "📈",
    "sell": "📉",
    "dividend": "🪙",
}

KEYWORD_ICON_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("food", "pizza", "restaurant", "bar", "coffee", "cafe", "grocery", "supermarket", "lunch", "dinner"), "🍽️"),
    (("transport", "metro", "train", "bus", "taxi", "fuel", "benzina", "diesel", "parking", "car", "auto"), "🚗"),
    (("rent", "house", "home", "mutuo", "mortgage", "condominio", "casa"), "🏠"),
    (("bill", "bolletta", "electric", "light", "water", "gas", "internet", "wifi", "phone"), "💡"),
    (("salary", "stipend", "income", "cedolino", "work", "job", "bonus"), "💼"),
    (("invest", "stock", "etf", "fund", "crypto", "trading", "portfolio"), "📈"),
    (("doctor", "health", "medicine", "pharmacy", "gym", "sport", "palestra"), "⚕️"),
    (("book", "study", "school", "university", "exam", "course", "kth", "polimi"), "📚"),
    (("gift", "present", "regalo"), "🎁"),
    (("travel", "flight", "hotel", "airbnb", "trip", "vacation", "viaggio"), "✈️"),
    (("subscription", "netflix", "spotify", "onedrive", "icloud", "amazon prime"), "🔁"),
    (("paypal", "card", "credit", "debt", "loan", "payable"), "💳"),
    (("charity", "donation", "zakat", "sadaqah", "mosque", "moschea"), "🤲"),
)


def load_category_icons_config(user_id: str | None = None) -> dict[str, Any]:
    return _normalize_icons(load_user_config(CATEGORY_ICONS_FILE, user_id=user_id))


def save_category_icons_config(config: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    return save_user_config(CATEGORY_ICONS_FILE, _normalize_icons(config), user_id=user_id)


def icon_for_category(category: Any, transaction_type: str | None = None, *, user_id: str | None = None, config: Mapping[str, Any] | None = None) -> str:
    name = _clean_category(category)
    if not name:
        return _type_default_icon(transaction_type)
    icons = _icon_lookup(config if config is not None else load_category_icons_config(user_id=user_id), transaction_type)
    configured = icons.get(_case_key(name))
    if configured:
        return configured
    return guess_icon_for_category(name, transaction_type)


def guess_icon_for_category(category: Any, transaction_type: str | None = None) -> str:
    name = _clean_category(category)
    key = _case_key(name)
    if key in DEFAULT_CATEGORY_ICONS:
        return DEFAULT_CATEGORY_ICONS[key]
    for keywords, icon in KEYWORD_ICON_RULES:
        if any(keyword in key for keyword in keywords):
            return icon
    return _type_default_icon(transaction_type)


def icons_for_categories_by_type(categories_by_type: Mapping[str, list[str]], user_id: str | None = None) -> dict[str, dict[str, str]]:
    config = load_category_icons_config(user_id=user_id)
    return {
        str(transaction_type): {
            str(category): icon_for_category(category, transaction_type, config=config)
            for category in categories
        }
        for transaction_type, categories in dict(categories_by_type or {}).items()
    }


def icon_map_for_categories(categories: list[str], transaction_type: str | None = None, user_id: str | None = None) -> dict[str, str]:
    config = load_category_icons_config(user_id=user_id)
    return {str(category): icon_for_category(category, transaction_type, config=config) for category in categories}


def set_category_icon(category: Any, icon: Any, transaction_type: str | None = None, user_id: str | None = None) -> dict[str, Any]:
    name = _clean_category(category)
    clean_icon = _clean_icon(icon)
    if not name:
        raise ValueError("Category name is required.")
    if not clean_icon:
        raise ValueError("Icon is required.")

    config = load_category_icons_config(user_id=user_id)
    key = _case_key(name)
    normalized_type = _normalize_transaction_type(transaction_type)
    if normalized_type:
        config.setdefault("types", {}).setdefault(normalized_type, {})[key] = clean_icon
    else:
        config.setdefault("icons", {})[key] = clean_icon
    return save_category_icons_config(config, user_id=user_id)


def category_option_rows(transaction_type: str, categories: list[str], user_id: str | None = None) -> list[dict[str, str]]:
    config = load_category_icons_config(user_id=user_id)
    return [
        {"name": str(category), "icon": icon_for_category(category, transaction_type, config=config)}
        for category in categories
    ]


def _normalize_icons(config: Mapping[str, Any]) -> dict[str, Any]:
    incoming = dict(config or {})
    clean: dict[str, Any] = {
        "schema_version": incoming.get("schema_version") or 1,
        "icons": _normalize_icon_mapping(incoming.get("icons", {})),
        "types": {},
        "updated_at": incoming.get("updated_at", ""),
    }
    raw_types = incoming.get("types", {}) if isinstance(incoming.get("types", {}), Mapping) else {}
    for transaction_type in app_categories.TRANSACTION_TYPES:
        clean["types"][transaction_type] = _normalize_icon_mapping(raw_types.get(transaction_type, {}))
    return clean


def _icon_lookup(config: Mapping[str, Any], transaction_type: str | None = None) -> dict[str, str]:
    normalized = _normalize_icons(config)
    lookup: dict[str, str] = {}
    lookup.update(DEFAULT_CATEGORY_ICONS)
    lookup.update(normalized.get("icons", {}))
    normalized_type = _normalize_transaction_type(transaction_type)
    if normalized_type:
        lookup.update(normalized.get("types", {}).get(normalized_type, {}))
    return lookup


def _normalize_icon_mapping(raw: Any) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        return {}
    result: dict[str, str] = {}
    for category, icon in raw.items():
        key = _case_key(category)
        clean_icon = _clean_icon(icon)
        if key and clean_icon:
            result[key] = clean_icon
    return result


def _normalize_transaction_type(transaction_type: str | None) -> str:
    value = str(transaction_type or "").strip().lower()
    return value if value in app_categories.TRANSACTION_TYPES else ""


def _clean_category(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _case_key(value: Any) -> str:
    return _clean_category(value).casefold()


def _clean_icon(value: Any) -> str:
    text = " ".join(str(value or "").strip().split())
    # Keep emoji/symbols short so table rows do not break if someone pastes text.
    return text[:12]


def _type_default_icon(transaction_type: str | None = None) -> str:
    normalized = _normalize_transaction_type(transaction_type)
    if normalized == "income":
        return "💰"
    if normalized == "investment":
        return "📈"
    return DEFAULT_ICON
