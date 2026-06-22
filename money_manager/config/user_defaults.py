"""Per-user configuration defaults for the Money Manager app.

These dictionaries are the source of truth for config files created under
``data/users/{user_id}/``. Service modules deep-copy these values before use so
callers can safely mutate loaded configs without modifying the defaults here.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

DEFAULT_PROFILE: dict[str, Any] = {
    "schema_version": 1,
    "first_name": "",
    "last_name": "",
    "display_name": "",
    "birth_year": "",
    "bank_name": "",
    "iban": "",
    "bic_swift": "",
    "default_main_account": "",
    "profile_image": "",
    "created_at": "",
    "updated_at": "",
}

DEFAULT_PREFERENCES: dict[str, Any] = {
    "schema_version": 1,
    "theme": "day",
    "language": "en",
    "currency": "EUR",
    "date_format": "dd/mm/yyyy",
    "privacy_mode": False,
    "show_sensitive_data": True,
    "updated_at": "",
}

DEFAULT_CATEGORIES: dict[str, Any] = {
    "schema_version": 1,
    "expense": {"custom": [], "hidden": [], "default": "Other"},
    "income": {"custom": [], "hidden": [], "default": "Other"},
    "investment": {"custom": [], "hidden": [], "default": "Other"},
}

DEFAULT_CONTACTS: dict[str, Any] = {
    "schema_version": 1,
    "contacts": [],
}

DEFAULT_NAVIGATION: dict[str, Any] = {
    "schema_version": 1,
    "hidden_pages": [],
    "custom_order": {},
    "group_order": {},
    "collapsed_groups": [],
}

DEFAULT_DOCUMENT_TYPES: dict[str, Any] = {
    "schema_version": 1,
    "types": [
        {
            "id": "cedolini",
            "name": "Cedolini",
            "description": "Payslips and salary documents",
            "is_default": True,
            "is_active": True,
            "display_order": 10,
        },
        {
            "id": "detrazioni_fiscali",
            "name": "Detrazioni Fiscali",
            "description": "Tax deduction documents",
            "is_default": True,
            "is_active": True,
            "display_order": 20,
        },
    ],
}

USER_CONFIG_DEFAULTS: dict[str, dict[str, Any]] = {
    "profile.json": DEFAULT_PROFILE,
    "preferences.json": DEFAULT_PREFERENCES,
    "categories.json": DEFAULT_CATEGORIES,
    "contacts.json": DEFAULT_CONTACTS,
    "navigation.json": DEFAULT_NAVIGATION,
    "document_types.json": DEFAULT_DOCUMENT_TYPES,
}


def default_for(filename: str) -> dict[str, Any]:
    """Return a mutable deep copy of the default payload for a config file."""
    try:
        return deepcopy(USER_CONFIG_DEFAULTS[filename])
    except KeyError as exc:
        raise ValueError(f"Unknown user config file: {filename}") from exc
