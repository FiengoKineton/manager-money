"""Generic account routing helpers.

The codebase no longer defines user-specific accounts here.  The effective
account list is loaded from ``data/users/{user_id}/accounts.json`` through
``money_manager.services.account_config_service``.  This module keeps the old
public function names so existing services/templates continue to work.
"""

from __future__ import annotations

from typing import Any

MAIN_ACCOUNT_KEY = "main_bank"
MAIN_ACCOUNT_LABEL = "Mediolanum"
CREDIT_OPTION_KEY = "credit_card"
PAYPAL_ACCOUNT_KEY = "paypal"  # compatibility key only; PayPal must be configured per user.
PAYPAL_CREDIT_ACCOUNT_VALUE = "paypal_credit"
PAYPAL_CREDIT_ALIASES = {"paypal_credit", "paypal credit", "pay pal credit", "paypal card", "pay pal card"}
PAYPAL_OPTION_KEY = PAYPAL_ACCOUNT_KEY

MAIN_NET_SEPARATE = "separate_when_explicit"
MAIN_NET_AFFECTS = "affects_main_net"
MAIN_NET_CREDIT_PENDING = "credit_pending"

MAIN_ACCOUNT_ALIASES = {
    "",
    "auto",
    "bank",
    "main",
    "main bank",
    "main bank account",
    "bank account",
    "conto",
    "conto corrente",
}

CREDIT_ACCOUNT_ALIASES = {
    "credit",
    "card",
    "credit card",
    "credit cards",
    "card credit",
    "carta credito",
    "carta di credito",
    "visa",
    "mastercard",
    *PAYPAL_CREDIT_ALIASES,
}

LEGACY_KEY_ALIASES = {
    "ticket_restaurant": "other_account",
    "other_accounts": "other_account",
}


def _svc():
    from money_manager.services import account_config_service as service

    return service


def _clean_text(value) -> str:
    text = str(value or "").strip().casefold()
    if text in {"nan", "none", "null"}:
        return ""
    return " ".join(text.split())


def all_accounts(include_archived: bool = True, include_main: bool = True) -> list[dict[str, Any]]:
    return _svc().all_accounts(include_archived=include_archived, include_main=include_main)


def all_auxiliary_accounts(include_archived: bool = True) -> list[dict[str, Any]]:
    return _svc().all_accounts(include_archived=include_archived, include_main=False)


def active_auxiliary_accounts() -> list[dict[str, Any]]:
    return _svc().active_accounts(include_main=False)


def auxiliary_account_keys(include_archived: bool = True) -> set[str]:
    return _svc().non_main_account_keys(include_archived=include_archived)


def account_options_for_forms(include_credit: bool = True) -> list[dict[str, Any]]:
    options = [
        {
            "key": MAIN_ACCOUNT_KEY,
            "id": MAIN_ACCOUNT_KEY,
            "label": MAIN_ACCOUNT_LABEL,
            "display_label": MAIN_ACCOUNT_LABEL,
            "description": "Blank means this movement belongs to Mediolanum / the selected default current account.",
            "value": "",
            "kind": "main",
            "main_net_policy": MAIN_NET_AFFECTS,
            "payment_logic": {
                "schema_version": 1,
                "mode": "main_net",
                "default_method": "main_net",
                "allowed_methods": ["main_net"],
                "default_insufficient_action": "stop",
                "insufficient_actions": [],
                "show_method_selector": False,
                "can_pay_from": True,
                "affects_main_net_now": True,
                "creates_pending": False,
            },
            "payment_mode": "main_net",
        }
    ]
    for account in _svc().account_display_options(include_archived=False, include_containers=True):
        if not include_credit and (account.get("main_net_policy") == MAIN_NET_CREDIT_PENDING or account.get("type") == "credit_card" or account.get("account_kind") == "credit_card_liability"):
            continue
        account = dict(account)
        payment_logic = account.get("payment_logic") if isinstance(account.get("payment_logic"), dict) else {}
        account["payment_mode"] = str(payment_logic.get("mode") or "")
        if account.get("main_net_policy") == MAIN_NET_AFFECTS:
            account["kind"] = "main_net_account"
        options.append(account)
    return options


def account_options_for_analysis() -> list[dict[str, Any]]:
    return all_auxiliary_accounts(include_archived=True)


def category_aliases_by_key() -> dict[str, set[str]]:
    return _svc().category_aliases_by_key()


def normalize_account_key(value: str | None) -> str:
    text = _clean_text(value)
    if text in LEGACY_KEY_ALIASES:
        return LEGACY_KEY_ALIASES[text]
    return _svc().normalize_account_key(value)


def is_main_account_value(value: str | None) -> bool:
    text = _clean_text(value)
    return text in MAIN_ACCOUNT_ALIASES


def account_parent_key(key: str | None) -> str:
    canonical = LEGACY_KEY_ALIASES.get(str(key or ""), str(key or ""))
    return _svc().account_parent_key(canonical)


def account_label_for_key(key: str | None) -> str:
    canonical = LEGACY_KEY_ALIASES.get(str(key or ""), str(key or ""))
    return _svc().account_label_for_key(canonical)


def account_description_for_key(key: str | None) -> str:
    canonical = LEGACY_KEY_ALIASES.get(str(key or ""), str(key or ""))
    return _svc().account_description_for_key(canonical)


def account_policy_for_key(key: str | None) -> str:
    canonical = LEGACY_KEY_ALIASES.get(str(key or ""), str(key or ""))
    return _svc().account_policy_for_key(canonical)


def account_due_day_for_key(key: str | None, default: int = 15) -> int:
    canonical = LEGACY_KEY_ALIASES.get(str(key or ""), str(key or ""))
    return _svc().account_due_day_for_key(canonical, default=default)


def account_label_for_value(value: str | None) -> str:
    raw = _clean_text(value)
    if raw in PAYPAL_CREDIT_ALIASES:
        return "PayPal credit route"
    return account_label_for_key(normalize_account_key(value))


def is_auxiliary_account(value: str | None) -> bool:
    key = normalize_account_key(value)
    return key in auxiliary_account_keys(include_archived=True)


def save_custom_account(label: str, description: str = "", aliases: str = "", category_aliases: str = "") -> dict | None:
    return _svc().create_account_from_form({
        "label": label,
        "description": description,
        "aliases": aliases,
        "category_aliases": category_aliases,
        "type": "wallet_balance",
        "account_kind": "wallet_balance",
        "main_net_policy": MAIN_NET_SEPARATE,
        "category_match_enabled": "1",
        "parent_account_id": "other_account",
    })


# Backward-compatible module variables.  They intentionally contain only generic
# app defaults at import time; dynamic screens must call the functions above.
try:
    AUXILIARY_ACCOUNTS = all_auxiliary_accounts(include_archived=True)
    AUXILIARY_ACCOUNT_KEYS = {account["key"] for account in AUXILIARY_ACCOUNTS}
    ACCOUNT_OPTIONS = account_options_for_forms()
except Exception:
    AUXILIARY_ACCOUNTS = []
    AUXILIARY_ACCOUNT_KEYS = set()
    ACCOUNT_OPTIONS = []
