from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from money_manager.services.account_config_service import (
    MAIN_NET_AFFECTS,
    MAIN_NET_CREDIT_PENDING,
    MAIN_NET_SEPARATE,
    account_by_key,
    clean_text,
    normalize_account_key,
)

PAYMENT_MODE_MAIN_NET = "main_net"
PAYMENT_MODE_TRACKED_BALANCE = "tracked_balance"
PAYMENT_MODE_CREDIT_STATEMENT = "credit_statement"
PAYMENT_MODE_CONTAINER = "container"

BALANCE_METHOD_BALANCE = "balance"
BALANCE_METHOD_CREDIT = "credit"
BALANCE_METHOD_ANOTHER_CARD = "another_card"
BALANCE_INSUFFICIENT_STOP = "stop"
BALANCE_INSUFFICIENT_ANOTHER_CARD = "use_another_card_for_remaining"
BALANCE_INSUFFICIENT_CREDIT = "use_credit_for_remaining"

_PAYMENT_METHOD_LABELS = {
    BALANCE_METHOD_BALANCE: "Use tracked balance first",
    BALANCE_METHOD_CREDIT: "Credit / card route",
    BALANCE_METHOD_ANOTHER_CARD: "Another card / main bank route",
}

_INSUFFICIENT_ACTION_LABELS = {
    BALANCE_INSUFFICIENT_STOP: "Stop and let me change method",
    BALANCE_INSUFFICIENT_ANOTHER_CARD: "Use balance, then another card/main bank for the rest",
    BALANCE_INSUFFICIENT_CREDIT: "Use balance, then credit for the rest",
}


def default_payment_logic_for_account(account: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return the default routing rules for an account record.

    This is the central place where payment behavior is derived from the account
    policy stored in ``accounts.json``. Payment forms should read this policy
    instead of guessing behavior from account names such as PayPal or Credit.
    """
    account = dict(account or {})
    policy = clean_text(account.get("main_net_policy") or MAIN_NET_SEPARATE)
    account_type = clean_text(account.get("type") or "wallet")
    account_kind = clean_text(account.get("account_kind") or account_type)
    is_container = bool(account.get("is_container")) or account_kind == "container"

    if policy == MAIN_NET_AFFECTS or account_type == "main" or account_kind == "current_account":
        return {
            "schema_version": 1,
            "mode": PAYMENT_MODE_MAIN_NET,
            "default_method": "main_net",
            "allowed_methods": ["main_net"],
            "default_insufficient_action": BALANCE_INSUFFICIENT_STOP,
            "insufficient_actions": [],
            "show_method_selector": False,
            "can_pay_from": True,
            "affects_main_net_now": True,
            "creates_pending": False,
        }

    if policy == MAIN_NET_CREDIT_PENDING or account_type == "credit_card" or account_kind == "credit_card_liability":
        return {
            "schema_version": 1,
            "mode": PAYMENT_MODE_CREDIT_STATEMENT,
            "default_method": BALANCE_METHOD_CREDIT,
            "allowed_methods": [BALANCE_METHOD_CREDIT],
            "default_insufficient_action": BALANCE_INSUFFICIENT_STOP,
            "insufficient_actions": [],
            "show_method_selector": False,
            "can_pay_from": True,
            "affects_main_net_now": False,
            "creates_pending": True,
        }

    if is_container:
        return {
            "schema_version": 1,
            "mode": PAYMENT_MODE_CONTAINER,
            "default_method": BALANCE_METHOD_BALANCE,
            "allowed_methods": [BALANCE_METHOD_BALANCE],
            "default_insufficient_action": BALANCE_INSUFFICIENT_STOP,
            "insufficient_actions": [BALANCE_INSUFFICIENT_STOP],
            "show_method_selector": False,
            "can_pay_from": False,
            "affects_main_net_now": False,
            "creates_pending": False,
        }

    return {
        "schema_version": 1,
        "mode": PAYMENT_MODE_TRACKED_BALANCE,
        "default_method": BALANCE_METHOD_BALANCE,
        "allowed_methods": [BALANCE_METHOD_BALANCE, BALANCE_METHOD_CREDIT, BALANCE_METHOD_ANOTHER_CARD],
        "default_insufficient_action": BALANCE_INSUFFICIENT_STOP,
        "insufficient_actions": [
            BALANCE_INSUFFICIENT_STOP,
            BALANCE_INSUFFICIENT_ANOTHER_CARD,
            BALANCE_INSUFFICIENT_CREDIT,
        ],
        "show_method_selector": True,
        "can_pay_from": True,
        "affects_main_net_now": False,
        "creates_pending": False,
    }


def normalize_payment_logic(raw: Any, account: Mapping[str, Any] | None) -> dict[str, Any]:
    default = default_payment_logic_for_account(account)
    if not isinstance(raw, Mapping):
        return default

    logic = deepcopy(default)
    mode = clean_text(raw.get("mode") or logic.get("mode"))
    if mode in {PAYMENT_MODE_MAIN_NET, PAYMENT_MODE_TRACKED_BALANCE, PAYMENT_MODE_CREDIT_STATEMENT, PAYMENT_MODE_CONTAINER}:
        logic["mode"] = mode

    allowed = _clean_list(raw.get("allowed_methods"))
    if allowed:
        logic["allowed_methods"] = allowed

    default_method = clean_text(raw.get("default_method") or logic.get("default_method"))
    if default_method in set(logic.get("allowed_methods") or []):
        logic["default_method"] = default_method

    insufficient = _clean_list(raw.get("insufficient_actions"))
    if insufficient:
        logic["insufficient_actions"] = insufficient

    default_action = clean_text(raw.get("default_insufficient_action") or logic.get("default_insufficient_action"))
    if default_action in set(logic.get("insufficient_actions") or []) or not logic.get("insufficient_actions"):
        logic["default_insufficient_action"] = default_action or BALANCE_INSUFFICIENT_STOP

    for key in ["show_method_selector", "can_pay_from", "affects_main_net_now", "creates_pending"]:
        if key in raw:
            logic[key] = bool(raw.get(key))

    return logic


def account_payment_logic_for_key(account_key: str | None, user_id: str | None = None) -> dict[str, Any]:
    key = normalize_account_key(account_key, user_id=user_id)
    account = account_by_key(key, user_id=user_id, include_archived=True)
    if not account:
        # Unknown keys fall back to main-net behavior only when the normalized key
        # is main_bank. Otherwise use a safe tracked-balance default; callers that
        # validate account IDs should reject unknown accounts before saving.
        if key == "main_bank":
            return default_payment_logic_for_account({"key": "main_bank", "type": "current_account", "account_kind": "current_account", "main_net_policy": MAIN_NET_AFFECTS})
        return default_payment_logic_for_account({"key": key, "main_net_policy": MAIN_NET_SEPARATE})
    return normalize_payment_logic(account.get("payment_logic"), account)


def resolve_payment_selection(
    account_key: str | None,
    *,
    payment_method: str | None = None,
    insufficient_action: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    logic = account_payment_logic_for_key(account_key, user_id=user_id)
    allowed_methods = set(logic.get("allowed_methods") or [])
    method = clean_text(payment_method or "")
    if not method or method not in allowed_methods:
        method = str(logic.get("default_method") or BALANCE_METHOD_BALANCE)

    allowed_actions = set(logic.get("insufficient_actions") or [])
    action = clean_text(insufficient_action or "")
    if not action or (allowed_actions and action not in allowed_actions):
        action = str(logic.get("default_insufficient_action") or BALANCE_INSUFFICIENT_STOP)

    return {
        "logic": logic,
        "payment_method": method,
        "insufficient_action": action,
    }


def payment_selection_from_form(form: Mapping[str, Any], account_key: str | None = None) -> dict[str, Any]:
    """Read generic account-payment fields, with old PayPal names as fallback."""
    method = (
        form.get("account_payment_method")
        or form.get("payment_method_route")
        or form.get("paypal_payment_method")
        or ""
    )
    action = (
        form.get("account_insufficient_action")
        or form.get("insufficient_action")
        or form.get("paypal_insufficient_action")
        or ""
    )
    return resolve_payment_selection(account_key, payment_method=str(method or ""), insufficient_action=str(action or ""))


def payment_method_options() -> list[dict[str, str]]:
    return [{"value": value, "label": label} for value, label in _PAYMENT_METHOD_LABELS.items()]


def insufficient_action_options() -> list[dict[str, str]]:
    return [{"value": value, "label": label} for value, label in _INSUFFICIENT_ACTION_LABELS.items()]


def _clean_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = clean_text(item)
        if text and text not in seen:
            result.append(text)
            seen.add(text)
    return result
