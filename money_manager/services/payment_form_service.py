from __future__ import annotations

"""Shared account/payment-method form helpers for Prompt 11F.

The UI should distinguish:
- Account / Conto: where a balance lives.
- Payment Method / Metodo di pagamento: how a movement is paid/routed.

These helpers return plain dictionaries that are safe to pass to templates and
JSON. They deliberately do not duplicate payment posting logic; real money
movement still goes through payment_routing_service.resolve_payment().
"""

import json
from typing import Any, Mapping

from money_manager.services.account_config_service import (
    MAIN_ACCOUNT_KEY,
    account_by_key,
    account_label_for_key,
    active_accounts,
    all_accounts,
    clean_text,
    normalize_account_key,
)
from money_manager.services.payment_method_service import (
    active_payment_methods,
    all_payment_methods,
    payment_method_by_id,
)

CURRENT_ACCOUNT_KINDS = {"current_account"}
BALANCE_ACCOUNT_KINDS = {
    "current_account",
    "cash",
    "prepaid_balance",
    "wallet_balance",
    "dependent_wallet",
    "meal_voucher",
    "investment_cash",
    "other",
}
DEPENDENT_ACCOUNT_KINDS = {"dependent_wallet", "wallet_balance", "prepaid_balance", "meal_voucher"}


def account_options_for_payment_forms(*, include_archived: bool = False, include_credit: bool = False, user_id: str | None = None) -> list[dict[str, Any]]:
    """Options for fields that mean real balance containers."""
    rows = all_accounts(user_id=user_id, include_archived=include_archived, include_main=True)
    options: list[dict[str, Any]] = []
    for account in rows:
        kind = str(account.get("account_kind") or account.get("type") or "")
        is_credit = kind == "credit_card_liability"
        if is_credit and not include_credit:
            continue
        if account.get("is_container"):
            continue
        key = str(account.get("key") or account.get("id") or "")
        label = str(account.get("label") or account.get("name") or key)
        parent = str(account.get("parent_account_id") or account.get("parent_key") or "")
        description = str(account.get("description") or "")
        if parent:
            parent_label = account_label_for_key(parent, user_id=user_id)
            label = f"{parent_label} / {label}"
        disabled_reason = ""
        if account.get("is_archived") or account.get("is_closed") or not account.get("is_active", True):
            disabled_reason = "Archived or closed account"
        options.append({
            "id": key,
            "value": key,
            "key": key,
            "label": label,
            "description": description,
            "method_type": "",
            "settlement_mode": "",
            "linked_account_id": "",
            "funding_account_id": key,
            "settlement_account_id": key,
            "liability_account_id": key if is_credit else "",
            "account_kind": kind,
            "is_credit_liability": is_credit,
            "is_archived": bool(account.get("is_archived") or account.get("is_closed") or not account.get("is_active", True)),
            "disabled_reason": disabled_reason,
            "display_order": account.get("display_order", 1000),
        })
    return sorted(options, key=lambda item: (_order(item.get("display_order")), str(item.get("label") or "")))


def current_account_options(user_id: str | None = None) -> list[dict[str, Any]]:
    return [
        option for option in account_options_for_payment_forms(user_id=user_id)
        if option.get("id") == MAIN_ACCOUNT_KEY or option.get("account_kind") in CURRENT_ACCOUNT_KINDS
    ]


def dependent_account_options(user_id: str | None = None) -> list[dict[str, Any]]:
    return [
        option for option in account_options_for_payment_forms(user_id=user_id)
        if option.get("account_kind") in DEPENDENT_ACCOUNT_KINDS
    ]


def payment_method_options_for_forms(*, include_archived: bool = False, selected_account_id: str | None = None, user_id: str | None = None) -> list[dict[str, Any]]:
    methods = all_payment_methods(include_archived=include_archived, user_id=user_id) if include_archived else active_payment_methods(user_id=user_id)
    selected = _stable_account_id(selected_account_id, user_id=user_id)
    options = [_method_option(method, selected_account_id=selected, user_id=user_id) for method in methods]

    # On add/edit transaction pages, selecting a Conto should show only the
    # cards/balances/payment rails that actually belong to that Conto.  The old
    # behavior showed every method with "Uses another account", which was noisy
    # and made it too easy to post Bank1 expenses through Bank2/PayPal by mistake.
    if selected and not include_archived:
        options = [option for option in options if not option.get("disabled_reason")]

    return sorted(options, key=lambda item: (_order(item.get("display_order")), str(item.get("label") or "")))


def compatible_payment_methods_for_account(account_id: str | None, user_id: str | None = None) -> list[dict[str, Any]]:
    return payment_method_options_for_forms(selected_account_id=account_id, user_id=user_id)


def default_payment_method_for_account(account_id: str | None, user_id: str | None = None) -> str:
    options = compatible_payment_methods_for_account(account_id, user_id=user_id)
    for option in options:
        if option.get("disabled_reason"):
            continue
        if option.get("is_default"):
            return str(option.get("id") or "")
    for option in options:
        if not option.get("disabled_reason"):
            return str(option.get("id") or "")
    return ""


def explain_payment_method(method_id: str | None, user_id: str | None = None) -> str:
    method = payment_method_by_id(str(method_id or ""), include_archived=True, user_id=user_id) if method_id else None
    if not method:
        return "Select a payment method to preview its route."
    return _explain_method(method, user_id=user_id)


def payment_form_context(transaction_type: str | None = None, selected_account_id: str | None = None, selected_payment_method_id: str | None = None, user_id: str | None = None) -> dict[str, Any]:
    tx_type = clean_text(transaction_type or "expense") or "expense"
    account_id = _stable_account_id(selected_account_id, user_id=user_id) or MAIN_ACCOUNT_KEY
    method_id = str(selected_payment_method_id or "").strip()
    if not method_id and tx_type in {"expense", "investment"}:
        method_id = default_payment_method_for_account(account_id, user_id=user_id)

    accounts = account_options_for_payment_forms(include_credit=False, user_id=user_id)
    payment_methods = payment_method_options_for_forms(selected_account_id=account_id, user_id=user_id)
    methods_by_account = {
        str(account.get("id") or ""): payment_method_options_for_forms(selected_account_id=str(account.get("id") or ""), user_id=user_id)
        for account in accounts
        if account.get("id")
    }
    by_id = {item.get("id"): item for item in payment_methods}
    selected_method = by_id.get(method_id) or (payment_methods[0] if payment_methods else {})
    if selected_method and not method_id:
        method_id = str(selected_method.get("id") or "")

    context = {
        "payment_form": {
            "transaction_type": tx_type,
            "selected_account_id": account_id,
            "selected_payment_method_id": method_id,
            "account_options": accounts,
            "current_account_options": current_account_options(user_id=user_id),
            "dependent_account_options": dependent_account_options(user_id=user_id),
            "payment_method_options": payment_methods,
            "payment_methods_by_account": methods_by_account,
            "selected_payment_method_explanation": explain_payment_method(method_id, user_id=user_id),
            "income_requires_account": tx_type == "income",
            "expense_requires_payment_method": tx_type == "expense",
            "investment_uses_funding_source": tx_type == "investment",
        },
    }
    context["payment_form_json"] = json.dumps(context["payment_form"], ensure_ascii=False)
    return context


def legacy_account_value_for_account_id(account_id: str | None, user_id: str | None = None) -> str:
    key = _stable_account_id(account_id, user_id=user_id)
    return "" if key == MAIN_ACCOUNT_KEY else key


def snapshot_account(account_id: str | None, user_id: str | None = None) -> dict[str, str]:
    key = _stable_account_id(account_id, user_id=user_id)
    return {"account_id": key, "account_name_snapshot": account_label_for_key(key, user_id=user_id) if key else ""}


def snapshot_payment_method(method_id: str | None, user_id: str | None = None) -> dict[str, str]:
    method = payment_method_by_id(str(method_id or ""), include_archived=True, user_id=user_id) if method_id else None
    return {
        "payment_method_id": str((method or {}).get("id") or method_id or ""),
        "payment_method_name_snapshot": str((method or {}).get("name") or method_id or ""),
    }


def _method_option(method: Mapping[str, Any], *, selected_account_id: str | None, user_id: str | None) -> dict[str, Any]:
    method_id = str(method.get("id") or "")
    selected = _stable_account_id(selected_account_id, user_id=user_id)
    disabled_reason = ""
    if method.get("is_archived") or not method.get("is_active", True):
        disabled_reason = "Archived payment method"
    elif selected and not _method_is_compatible_with_account(method, selected, user_id=user_id):
        disabled_reason = "Uses another account"
    if method.get("validation_errors"):
        disabled_reason = ", ".join(str(err) for err in method.get("validation_errors") or [])
    return {
        "id": method_id,
        "value": method_id,
        "label": str(method.get("name") or method_id),
        "description": _explain_method(method, user_id=user_id),
        "method_type": str(method.get("method_type") or ""),
        "settlement_mode": str(method.get("settlement_mode") or ""),
        "linked_account_id": str(method.get("linked_account_id") or ""),
        "funding_account_id": str(method.get("funding_account_id") or ""),
        "settlement_account_id": str(method.get("settlement_account_id") or ""),
        "liability_account_id": str(method.get("liability_account_id") or ""),
        "delegates_to_payment_method_id": str(method.get("delegates_to_payment_method_id") or ""),
        "rules": dict(method.get("rules") if isinstance(method.get("rules"), Mapping) else {}),
        "due_day": (method.get("rules") if isinstance(method.get("rules"), Mapping) else {}).get("due_day"),
        "statement_day": (method.get("rules") if isinstance(method.get("rules"), Mapping) else {}).get("statement_day"),
        "settlement_day_policy": (method.get("rules") if isinstance(method.get("rules"), Mapping) else {}).get("settlement_day_policy", "next_month"),
        "aliases": list(method.get("aliases") or []),
        "is_default": bool(method.get("is_default")),
        "is_archived": bool(method.get("is_archived") or not method.get("is_active", True)),
        "disabled_reason": disabled_reason,
        "display_order": method.get("display_order", 1000),
    }


def _explain_method(method: Mapping[str, Any], *, user_id: str | None) -> str:
    name = str(method.get("name") or method.get("id") or "This method")
    method_type = str(method.get("method_type") or "")
    mode = str(method.get("settlement_mode") or "")
    linked = str(method.get("linked_account_id") or "")
    funding = str(method.get("funding_account_id") or linked or "")
    settlement = str(method.get("settlement_account_id") or funding or "")
    liability = str(method.get("liability_account_id") or "")
    if mode == "delegated":
        delegate_id = str(method.get("delegates_to_payment_method_id") or "")
        delegate = payment_method_by_id(delegate_id, include_archived=True, user_id=user_id) if delegate_id else None
        return f"{name} delegates to {(delegate or {}).get('name') or delegate_id or 'another payment method'}."
    if mode == "delayed" or method_type == "credit_card":
        rules = method.get("rules") if isinstance(method.get("rules"), Mapping) else {}
        due_day = rules.get("due_day") or 15
        settle_label = account_label_for_key(settlement, user_id=user_id) if settlement else "the configured settlement account"
        liability_label = account_label_for_key(liability, user_id=user_id) if liability else "credit-card liability"
        return f"{name} increases {liability_label} now and will be settled on day {due_day} from {settle_label}."
    if mode == "stored_balance":
        label = account_label_for_key(funding or linked, user_id=user_id) if (funding or linked) else "its stored balance"
        return f"{name} deducts immediately from {label}."
    if mode == "immediate":
        label = account_label_for_key(funding or MAIN_ACCOUNT_KEY, user_id=user_id)
        return f"{name} deducts immediately from {label}."
    return f"{name} records the payment without a tracked balance movement."


def _method_is_compatible_with_account(method: Mapping[str, Any], account_id: str, user_id: str | None = None) -> bool:
    if not account_id:
        return True

    def _refs(row: Mapping[str, Any]) -> set[str]:
        return {
            str(row.get("linked_account_id") or ""),
            str(row.get("funding_account_id") or ""),
            str(row.get("settlement_account_id") or ""),
            str(row.get("liability_account_id") or ""),
        }

    refs = _refs(method)
    if account_id in refs:
        return True

    method_type = str(method.get("method_type") or "")

    # Prepaid cards usually spend a hidden child balance account.  They should
    # still be selectable from the parent current account that owns/reloads that
    # card.  Normal wallets do not get this roll-up.
    if method_type == "prepaid_card":
        for ref in refs:
            if not ref:
                continue
            account = account_by_key(ref, user_id=user_id, include_archived=True) or {}
            parent = str(account.get("parent_account_id") or account.get("parent_key") or "")
            if parent == account_id:
                return True

    if method.get("settlement_mode") == "delegated":
        # Delegated wrappers belong to their visible linked account.  Example:
        # "PayPal via Main card" should appear under PayPal, not under Main, even
        # though its delegate ultimately charges a Main debit/credit card.
        return False

    return False


def _stable_account_id(value: str | None, *, user_id: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    account = account_by_key(text, user_id=user_id, include_archived=True)
    if account:
        return str(account.get("key") or account.get("id") or "")
    return normalize_account_key(text, user_id=user_id)


def _order(value: Any) -> int:
    try:
        return int(float(str(value).replace(",", ".")))
    except (TypeError, ValueError):
        return 1000
