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
    # Existing users repaired from older versions should not be forced into onboarding.
    # New users are explicitly set to False by user_manager.create_user().
    "onboarding_completed": True,
    "updated_at": "",
}

DEFAULT_CATEGORIES: dict[str, Any] = {
    "schema_version": 2,
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
    "group_order": [],
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


DEFAULT_ACCOUNTS: dict[str, Any] = {
    "schema_version": 2,
    "updated_at": "",
    "accounts": [
        {
            "id": "main_bank",
            "key": "main_bank",
            "name": "Main bank account",
            "label": "Main bank account",
            "type": "main",
            "currency": "EUR",
            "institution": "",
            "iban": "",
            "initial_balance": 0,
            "description": "Default route for ordinary transactions that affect the tracked main net balance.",
            "aliases": ["main", "main bank", "main bank account", "bank", "bank account", "auto"],
            "category_aliases": [],
            "category_match_enabled": False,
            "category_match_mode": "top_up_shadow",
            "main_net_policy": "affects_main_net",
            "parent_account_id": None,
            "parent_key": "",
            "is_container": False,
            "is_default": True,
            "is_custom": False,
            "is_active": True,
            "display_order": 0,
            "cards": [],
            "metadata": {},
        },
        {
            "id": "cash_flow",
            "key": "cash_flow",
            "name": "Cash Flow",
            "label": "Cash Flow",
            "type": "cash",
            "currency": "EUR",
            "institution": "",
            "iban": "",
            "initial_balance": 0,
            "description": "Generic cash or wallet balance tracked separately from the main route.",
            "aliases": ["cash", "cash flow", "wallet"],
            "category_aliases": ["cash", "cash flow"],
            "category_match_enabled": True,
            "category_match_mode": "top_up_shadow",
            "main_net_policy": "separate_when_explicit",
            "parent_account_id": None,
            "parent_key": "",
            "is_container": False,
            "is_default": True,
            "is_custom": False,
            "is_active": True,
            "display_order": 10,
            "cards": [],
            "metadata": {},
        },
        {
            "id": "credit_card",
            "key": "credit_card",
            "name": "Credit Card",
            "label": "Credit Card",
            "type": "credit_card",
            "currency": "EUR",
            "institution": "",
            "iban": "",
            "initial_balance": 0,
            "description": "Default credit-card route. Credit-card purchases are tracked on the real charge date, then grouped into one monthly pending statement.",
            "aliases": [
                "credit",
                "credit card",
                "credit cards",
                "card credit",
                "carta credito",
                "carta di credito",
            ],
            "category_aliases": [
                "credit",
                "credit card",
                "credit cards",
                "card credit",
                "carta credito",
                "carta di credito",
            ],
            "category_match_enabled": True,
            "category_match_mode": "credit_pending",
            "main_net_policy": "credit_pending",
            "parent_account_id": None,
            "parent_key": "",
            "is_container": False,
            "is_default": True,
            "is_custom": False,
            "is_active": True,
            "display_order": 20,
            "due_day": 15,
            "statement_day": None,
            "cards": [],
            "metadata": {},
        },
        {
            "id": "other_account",
            "key": "other_account",
            "name": "Other Accounts",
            "label": "Other Accounts",
            "type": "container",
            "currency": "EUR",
            "institution": "",
            "iban": "",
            "initial_balance": 0,
            "description": "Container for smaller temporary accounts. Child balances are aggregated here.",
            "aliases": ["other account", "other accounts", "small accounts", "small account"],
            "category_aliases": ["other account", "other accounts", "small accounts", "small account"],
            "category_match_enabled": True,
            "category_match_mode": "top_up_shadow",
            "main_net_policy": "separate_when_explicit",
            "parent_account_id": None,
            "parent_key": "",
            "is_container": True,
            "is_default": True,
            "is_custom": False,
            "is_active": True,
            "display_order": 30,
            "cards": [],
            "metadata": {},
        },
    ],
}

USER_CONFIG_DEFAULTS: dict[str, dict[str, Any]] = {
    "profile.json": DEFAULT_PROFILE,
    "preferences.json": DEFAULT_PREFERENCES,
    "categories.json": DEFAULT_CATEGORIES,
    "accounts.json": DEFAULT_ACCOUNTS,
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
