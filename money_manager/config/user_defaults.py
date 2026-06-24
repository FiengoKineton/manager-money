"""Per-user configuration defaults for the Money Manager app.

These dictionaries are the source of truth for config files created under
``data/users/{user_id}/``. Service modules deep-copy these values before use so
callers can safely mutate loaded configs without modifying the defaults here.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

DEFAULT_PROFILE: dict[str, Any] = {
    "schema_version": 2,
    # Personal identity. Profile represents the user, not a single bank account.
    "first_name": "",
    "last_name": "",
    "display_name": "",
    "birth_year": "",
    "profile_image": "",
    "profile_notes": "",
    # User-level defaults that point to the account/payment architecture.
    "default_current_account_id": "main_bank",
    "default_payment_method_id": "",
    "onboarding_completed": True,
    # Deprecated compatibility fields. They are kept during migration so old
    # pages/imports do not break, but bank ownership now lives on accounts.json.
    "bank_name": "",
    "iban": "",
    "bic_swift": "",
    "default_main_account": "",
    "deprecated_fields": ["bank_name", "iban", "bic_swift", "default_main_account"],
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


def _account(
    *,
    account_id: str,
    name: str,
    account_kind: str,
    display_order: int,
    description: str,
    aliases: list[str] | None = None,
    category_aliases: list[str] | None = None,
    main_net_policy: str = "separate_when_explicit",
    is_current_account: bool = False,
    is_financial_center: bool | None = None,
    liquidity_rollup_policy: str | None = None,
    is_liability: bool = False,
    is_container: bool = False,
    is_default: bool = True,
    due_day: int | None = None,
    statement_day: int | None = None,
) -> dict[str, Any]:
    if is_financial_center is None:
        is_financial_center = bool(is_current_account and not is_liability and not is_container)
    if liquidity_rollup_policy is None:
        liquidity_rollup_policy = "own_only"

    return {
        "id": account_id,
        "key": account_id,
        "name": name,
        "label": name,
        "account_kind": account_kind,
        "type": account_kind,
        "currency": "EUR",
        "institution": "",
        "iban": "",
        "bic_swift": "",
        "initial_balance": 0.0,
        "description": description,
        "is_current_account": is_current_account,
        "is_financial_center": bool(is_financial_center),
        "is_dependent_account": False,
        "parent_account_id": "",
        "parent_key": "",
        "liquidity_rollup_policy": liquidity_rollup_policy,
        "is_liability": is_liability,
        "is_container": is_container,
        "is_default": is_default,
        "is_custom": not is_default,
        "is_active": True,
        "is_closed": False,
        "closed_at": "",
        "replacement_account_id": "",
        "display_order": display_order,
        "aliases": aliases or [],
        "category_aliases": category_aliases or [],
        "category_match_enabled": bool(category_aliases),
        "category_match_mode": "credit_pending" if main_net_policy == "credit_pending" else "top_up_shadow",
        "main_net_policy": main_net_policy,
        "metadata": {},
        "legacy": {},
        "created_at": "",
        "updated_at": "",
        "archived_at": "",
        # Legacy compatibility fields retained during the 11B transition.
        "payment_logic": {},
        "due_day": due_day,
        "statement_day": statement_day,
        "cards": [],
    }


DEFAULT_ACCOUNTS: dict[str, Any] = {
    "schema_version": 3,
    "updated_at": "",
    "accounts": [
        _account(
            account_id="main_bank",
            name="Primary current account",
            account_kind="current_account",
            display_order=0,
            description="Default current account route for ordinary transactions that affect the tracked global net balance.",
            aliases=["main", "main bank", "main bank account", "bank", "bank account", "auto", "conto", "conto corrente"],
            main_net_policy="affects_main_net",
            is_current_account=True,
            is_financial_center=True,
            liquidity_rollup_policy="own_only",
        ),
        _account(
            account_id="cash_flow",
            name="Cash Flow",
            account_kind="cash",
            display_order=10,
            description="Generic physical-cash balance tracked separately from the main route.",
            aliases=["cash", "cash flow", "wallet", "contanti"],
            category_aliases=["cash", "cash flow", "contanti"],
            is_financial_center=False,
            liquidity_rollup_policy="own_only",
        ),
        _account(
            account_id="other_account",
            name="Other Accounts",
            account_kind="container",
            display_order=30,
            description="Container for smaller temporary accounts. Child balances are aggregated here.",
            aliases=["other account", "other accounts", "small accounts", "small account"],
            category_aliases=["other account", "other accounts", "small accounts", "small account"],
            is_container=True,
            is_financial_center=False,
            liquidity_rollup_policy="own_only",
        ),
    ],
}

DEFAULT_PAYMENT_METHODS: dict[str, Any] = {
    "schema_version": 1,
    "payment_methods": [
        {
            "id": "main_bank_debit_card",
            "name": "Debit Card",
            "method_type": "debit_card",
            "linked_account_id": "main_bank",
            "funding_account_id": "main_bank",
            "settlement_account_id": "main_bank",
            "liability_account_id": "",
            "settlement_mode": "immediate",
            "delegates_to_payment_method_id": "",
            "is_default": True,
            "is_active": True,
            "is_archived": False,
            "display_order": 0,
            "rules": {
                "due_day": None,
                "statement_day": None,
                "settlement_day_policy": "next_month",
                "allow_manual_due_date": True,
            },
            "aliases": ["debit", "debit card", "card", "main card", "carta", "bancomat"],
            "legacy": {},
            "metadata": {"auto_default": True, "visible_card": True},
            "created_at": "",
            "updated_at": "",
            "archived_at": "",
        },
        {
            "id": "main_bank_transfer",
            "name": "Bank Transfer",
            "method_type": "bank_transfer",
            "linked_account_id": "main_bank",
            "funding_account_id": "main_bank",
            "settlement_account_id": "main_bank",
            "liability_account_id": "",
            "settlement_mode": "immediate",
            "delegates_to_payment_method_id": "",
            "is_default": False,
            "is_active": True,
            "is_archived": False,
            "display_order": 5,
            "rules": {
                "due_day": None,
                "statement_day": None,
                "settlement_day_policy": "next_month",
                "allow_manual_due_date": True,
            },
            "aliases": ["bank", "bank transfer", "bonifico"],
            "legacy": {},
            "metadata": {"auto_default": True, "visible_card": False},
            "created_at": "",
            "updated_at": "",
            "archived_at": "",
        },
        {
            "id": "cash",
            "name": "Cash",
            "method_type": "cash",
            "linked_account_id": "cash_flow",
            "funding_account_id": "cash_flow",
            "settlement_account_id": "cash_flow",
            "liability_account_id": "",
            "settlement_mode": "stored_balance",
            "delegates_to_payment_method_id": "",
            "is_default": False,
            "is_active": True,
            "is_archived": False,
            "display_order": 10,
            "rules": {
                "due_day": None,
                "statement_day": None,
                "settlement_day_policy": "next_month",
                "allow_manual_due_date": True,
            },
            "aliases": ["cash", "cash flow", "contanti"],
            "legacy": {},
            "metadata": {},
            "created_at": "",
            "updated_at": "",
            "archived_at": "",
        },
    ],
}
DEFAULT_RECEIPTS: dict[str, Any] = {
    "schema_version": 1,
    "receipts": {},
    "updated_at": "",
}

USER_CONFIG_DEFAULTS: dict[str, dict[str, Any]] = {
    "profile.json": DEFAULT_PROFILE,
    "preferences.json": DEFAULT_PREFERENCES,
    "categories.json": DEFAULT_CATEGORIES,
    "accounts.json": DEFAULT_ACCOUNTS,
    "payment_methods.json": DEFAULT_PAYMENT_METHODS,
    "contacts.json": DEFAULT_CONTACTS,
    "navigation.json": DEFAULT_NAVIGATION,
    "document_types.json": DEFAULT_DOCUMENT_TYPES,
    "receipts.json": DEFAULT_RECEIPTS,
}


def default_for(filename: str) -> dict[str, Any]:
    """Return a mutable deep copy of the default payload for a config file."""
    try:
        return deepcopy(USER_CONFIG_DEFAULTS[filename])
    except KeyError as exc:
        raise ValueError(f"Unknown user config file: {filename}") from exc
