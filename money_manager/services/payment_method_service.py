from __future__ import annotations

import os, re
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from money_manager.config.user_defaults import DEFAULT_PAYMENT_METHODS
from money_manager.config.user_paths import get_current_user_id, get_user_data_dir, normalize_user_id
from money_manager.security.protection_manager import read_json, write_json_atomic
from money_manager.services._user_config import config_path, load_user_config, save_user_config

PAYMENT_METHODS_FILE = "payment_methods.json"

METHOD_TYPES = {
    "debit_card",
    "credit_card",
    "prepaid_card",
    "wallet_balance",
    "wallet_linked_card",
    "bank_transfer",
    "cash",
    "meal_voucher",
    "investment_cash_transfer",
    "other",
}

SETTLEMENT_MODES = {
    "immediate",
    "delayed",
    "stored_balance",
    "delegated",
    "external_record_only",
}

_ACCOUNT_REQUIRED_BY_MODE = {
    "immediate": ("funding_account_id",),
    "delayed": ("funding_account_id", "settlement_account_id", "liability_account_id"),
    "stored_balance": ("linked_account_id", "funding_account_id"),
    "delegated": ("delegates_to_payment_method_id",),
    "external_record_only": (),
}

def _repair_config_on_read_enabled() -> bool:
    return os.environ.get("MONEY_MANAGER_REPAIR_CONFIG_ON_READ", "0").strip() == "1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean_text(value: Any) -> str:
    text = str(value or "").strip().casefold()
    if text in {"nan", "none", "null"}:
        return ""
    return " ".join(text.split())


def clean_label(value: Any) -> str:
    text = str(value or "").strip()
    if text.casefold() in {"nan", "none", "null"}:
        return ""
    return " ".join(text.split())


def slugify(value: Any) -> str:
    text = clean_text(value)
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or f"payment_method_{uuid.uuid4().hex[:8]}"


def split_aliases(value: str | Iterable[str] | None) -> list[str]:
    if value is None:
        chunks: Iterable[Any] = []
    elif isinstance(value, str):
        chunks = re.split(r"[,;\n]", value)
    else:
        chunks = value
    result: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        alias = clean_text(chunk)
        if alias and alias not in seen:
            result.append(alias)
            seen.add(alias)
    return result


def _parse_optional_day(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        day = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return day if 1 <= day <= 31 else None


def load_payment_methods(user_id: str | None = None) -> dict[str, Any]:
    """Load and repair the current user's payment method configuration."""
    return ensure_payment_methods_file(user_id=user_id)


def save_payment_methods(payload: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    from money_manager.services.account_config_service import load_accounts_config

    accounts_payload = load_accounts_config(user_id=user_id)
    normalized = normalize_payment_methods_config(payload, accounts_payload=accounts_payload)
    normalized["updated_at"] = utc_now()
    try:
        from money_manager.cache import request_cache

        request_cache.delete_prefix("payment_method_lookup:")
    except Exception:
        pass
    return save_user_config(PAYMENT_METHODS_FILE, normalized, user_id=user_id)


def ensure_payment_methods_file(user_id: str | None = None) -> dict[str, Any]:
    """Create payment_methods.json from accounts.json when missing, then repair it.

    The first creation path is intentionally account-aware. A plain default file
    would lose important v10 routes such as pre-paid card, EdenRed, PayPal, and
    the credit-card liability bucket.
    """
    from money_manager.services.account_config_service import load_accounts_config

    accounts_payload = load_accounts_config(user_id=user_id)
    path = config_path(PAYMENT_METHODS_FILE, user_id=user_id)
    raw = read_json(path, None)
    created = raw is None
    if created:
        normalized = infer_default_payment_methods_from_accounts(accounts_payload)
    else:
        normalized = normalize_payment_methods_config(raw, accounts_payload=accounts_payload)
    normalized_with_account_methods = ensure_methods_for_accounts(normalized, accounts_payload)

    if (created or normalized_with_account_methods != raw) and _repair_config_on_read_enabled():
        save_user_config(PAYMENT_METHODS_FILE, normalized_with_account_methods, user_id=user_id)

    return normalized_with_account_methods


def _payment_lookup_user_key(user_id: str | None = None) -> str:
    try:
        current = user_id or get_current_user_id()
        return normalize_user_id(current) if current else ""
    except Exception:
        return str(user_id or "")


def _payment_method_lookup_snapshot(user_id: str | None = None) -> dict[str, Any]:
    """Return request-local payment method indexes for hot render paths.

    Forms and transaction rows frequently resolve the same payment method id,
    aliases, and active lists many times during a single request.  Build those
    maps once per request so encrypted config files are not repeatedly parsed and
    normalized while preserving the same payment-method schema and behavior.
    """
    cache_key = f"payment_method_lookup:{_payment_lookup_user_key(user_id)}"
    try:
        from money_manager.cache import request_cache

        sentinel = object()
        cached = request_cache.get(cache_key, sentinel)
        if cached is not sentinel:
            return cached
    except Exception:
        request_cache = None  # type: ignore

    methods = list(ensure_payment_methods_file(user_id=user_id).get("payment_methods", []) or [])
    by_id: dict[str, dict[str, Any]] = {}
    alias_map: dict[str, str] = {}
    for method in methods:
        if not isinstance(method, Mapping):
            continue
        method_id = str(method.get("id") or "")
        if method_id:
            by_id[method_id] = method
        for alias_value in [method.get("id"), method.get("name"), *method.get("aliases", [])]:
            alias = clean_text(alias_value)
            if alias and method_id:
                alias_map[alias] = method_id

    payload = {"methods": methods, "by_id": by_id, "alias_map": alias_map}
    try:
        request_cache.set(cache_key, payload)  # type: ignore[name-defined]
    except Exception:
        pass
    return payload


def all_payment_methods(include_archived: bool = True, user_id: str | None = None) -> list[dict[str, Any]]:
    methods = _payment_method_lookup_snapshot(user_id=user_id).get("methods", [])
    result: list[dict[str, Any]] = []
    for method in methods:
        if not include_archived and (method.get("is_archived") or not method.get("is_active", True)):
            continue
        result.append(method)
    return result


def active_payment_methods(user_id: str | None = None) -> list[dict[str, Any]]:
    return all_payment_methods(include_archived=False, user_id=user_id)


def payment_method_by_id(method_id: str, include_archived: bool = True, user_id: str | None = None) -> dict[str, Any] | None:
    wanted = normalize_payment_method_id(method_id, user_id=user_id)
    method = _payment_method_lookup_snapshot(user_id=user_id).get("by_id", {}).get(wanted)
    if not method:
        return None
    if not include_archived and (method.get("is_archived") or not method.get("is_active", True)):
        return None
    return method


def normalize_payment_method_id(value: str | None, user_id: str | None = None) -> str:
    text = clean_text(value)
    if not text:
        return ""
    mapping = _payment_method_lookup_snapshot(user_id=user_id).get("alias_map", {})
    return mapping.get(text, slugify(text))


def payment_method_options_for_forms(user_id: str | None = None) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    for method in active_payment_methods(user_id=user_id):
        options.append({
            "id": method.get("id"),
            "value": method.get("id"),
            "label": method.get("name") or method.get("id"),
            "method_type": method.get("method_type"),
            "settlement_mode": method.get("settlement_mode"),
            "linked_account_id": method.get("linked_account_id", ""),
            "funding_account_id": method.get("funding_account_id", ""),
            "settlement_account_id": method.get("settlement_account_id", ""),
            "liability_account_id": method.get("liability_account_id", ""),
            "display_order": method.get("display_order", 1000),
        })
    return sorted(options, key=lambda item: (_display_order_for_sort(item.get("display_order")), str(item.get("label") or "")))


def create_payment_method_from_form(form: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    payload = ensure_payment_methods_file(user_id=user_id)
    methods = list(payload.get("payment_methods", []))
    method_id = slugify(form.get("id") or form.get("name"))
    if any(method.get("id") == method_id for method in methods):
        return update_payment_method_from_form(method_id, form, user_id=user_id)
    method = _normalize_payment_method_record(_method_from_form(form, method_id=method_id), index=len(methods))
    methods.append(method)
    payload["payment_methods"] = methods
    save_payment_methods(payload, user_id=user_id)
    return method


def update_payment_method_from_form(method_id: str, form: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    payload = ensure_payment_methods_file(user_id=user_id)
    wanted = normalize_payment_method_id(method_id, user_id=user_id)
    methods = list(payload.get("payment_methods", []))
    for index, method in enumerate(methods):
        if method.get("id") != wanted:
            continue
        updated = dict(method)
        form_update = _method_from_form(form, method_id=wanted)
        if not form_update.get("metadata") and isinstance(updated.get("metadata"), Mapping):
            form_update.pop("metadata", None)
        updated.update(form_update)
        updated["updated_at"] = utc_now()
        methods[index] = _normalize_payment_method_record(updated, index=index)
        payload["payment_methods"] = methods
        save_payment_methods(payload, user_id=user_id)
        return methods[index]
    raise ValueError(f"Unknown payment method: {method_id}")


def archive_payment_method(method_id: str, user_id: str | None = None) -> bool:
    return _set_method_archived(method_id, archived=True, user_id=user_id)


def restore_payment_method(method_id: str, user_id: str | None = None) -> bool:
    return _set_method_archived(method_id, archived=False, user_id=user_id)


def validate_payment_method(method: Mapping[str, Any], accounts: Mapping[str, Any] | list[Mapping[str, Any]], methods: Mapping[str, Any] | list[Mapping[str, Any]]) -> list[str]:
    errors: list[str] = []
    method_id = str(method.get("id") or "")
    method_type = clean_text(method.get("method_type") or "")
    settlement_mode = clean_text(method.get("settlement_mode") or "")
    if not method_id:
        errors.append("missing_id")
    if method_type not in METHOD_TYPES:
        errors.append("invalid_method_type")
    if settlement_mode not in SETTLEMENT_MODES:
        errors.append("invalid_settlement_mode")

    account_ids = _account_ids(accounts)
    method_ids = _method_ids(methods)
    for field in _ACCOUNT_REQUIRED_BY_MODE.get(settlement_mode, ()):
        value = str(method.get(field) or "").strip()
        if not value:
            errors.append(f"missing_{field}")
        elif field == "delegates_to_payment_method_id":
            if value not in method_ids:
                errors.append("unknown_delegated_payment_method")
        elif value not in account_ids:
            errors.append(f"unknown_{field}")

    for field in ["linked_account_id", "funding_account_id", "settlement_account_id", "liability_account_id"]:
        value = str(method.get(field) or "").strip()
        if value and value not in account_ids:
            errors.append(f"unknown_{field}")

    if settlement_mode == "delegated":
        delegate = str(method.get("delegates_to_payment_method_id") or "")
        if delegate == method_id:
            errors.append("delegation_cycle")
        elif _delegation_has_cycle(method_id, delegate, methods):
            errors.append("delegation_cycle")
    return errors


def infer_default_payment_methods_from_accounts(accounts_payload: Mapping[str, Any]) -> dict[str, Any]:
    accounts = [dict(account) for account in accounts_payload.get("accounts", []) if isinstance(account, Mapping)]
    keys = {str(account.get("key") or account.get("id") or "") for account in accounts}
    by_key = {str(account.get("key") or account.get("id") or ""): account for account in accounts}
    methods: list[dict[str, Any]] = []

    def add(raw: Mapping[str, Any]) -> None:
        method = _normalize_payment_method_record(raw, index=len(methods))
        if method.get("id") not in {m.get("id") for m in methods}:
            methods.append(method)

    if "main_bank" in keys:
        add({
            "id": "main_bank_debit_card",
            "name": "Debit Card",
            "method_type": "debit_card",
            "settlement_mode": "immediate",
            "linked_account_id": "main_bank",
            "funding_account_id": "main_bank",
            "settlement_account_id": "main_bank",
            "display_order": 0,
            "aliases": ["debit", "debit card", "card", "main card", "bancomat"],
            "is_default": True,
            "legacy": {"migration_rule": "A.main_bank_debit_card"},
            "metadata": {"auto_default": True, "visible_card": True},
        })
        add({
            "id": "main_bank_transfer",
            "name": "Bank Transfer",
            "method_type": "bank_transfer",
            "settlement_mode": "immediate",
            "linked_account_id": "main_bank",
            "funding_account_id": "main_bank",
            "settlement_account_id": "main_bank",
            "display_order": 5,
            "aliases": ["main", "bank", "main bank", "bank transfer", "bonifico"],
            "legacy": {"migration_rule": "A.main_bank_transfer"},
            "metadata": {"auto_default": True, "visible_card": False},
        })
    if "cash_flow" in keys:
        add({
            "id": "cash",
            "name": "Cash",
            "method_type": "cash",
            "settlement_mode": "stored_balance",
            "linked_account_id": "cash_flow",
            "funding_account_id": "cash_flow",
            "settlement_account_id": "cash_flow",
            "display_order": 10,
            "aliases": ["cash", "cash flow", "contanti"],
            "legacy": {"migration_rule": "B.cash_flow"},
        })
    if "pre_paid_card" in keys:
        add({
            "id": "pre_paid_card",
            "name": "Pre-paid card",
            "method_type": "prepaid_card",
            "settlement_mode": "stored_balance",
            "linked_account_id": "pre_paid_card",
            "funding_account_id": "pre_paid_card",
            "settlement_account_id": "pre_paid_card",
            "display_order": 20,
            "aliases": ["pre-paid card", "prepaid card", "pre paid card", "postepay", "carta prepagata"],
            "legacy": {"migration_rule": "C.pre_paid_card"},
        })
    if "edenred" in keys:
        add({
            "id": "edenred",
            "name": "EdenRed",
            "method_type": "meal_voucher",
            "settlement_mode": "stored_balance",
            "linked_account_id": "edenred",
            "funding_account_id": "edenred",
            "settlement_account_id": "edenred",
            "display_order": 30,
            "aliases": ["edenred", "eden red", "edenred card", "buoni pasto"],
            "legacy": {"migration_rule": "D.edenred"},
        })
    if "paypal" in keys:
        add({
            "id": "paypal_balance",
            "name": "PayPal balance",
            "method_type": "wallet_balance",
            "settlement_mode": "stored_balance",
            "linked_account_id": "paypal",
            "funding_account_id": "paypal",
            "settlement_account_id": "paypal",
            "display_order": 40,
            "aliases": ["paypal", "pay pal", "paypal balance", "paypal wallet"],
            "legacy": {"migration_rule": "E.paypal"},
        })
    if "paypal" in keys and "main_bank" in keys:
        add({
            "id": "paypal_via_main_bank",
            "name": "PayPal via Main Bank card",
            "method_type": "wallet_linked_card",
            "settlement_mode": "delegated",
            "linked_account_id": "paypal",
            "delegates_to_payment_method_id": "main_bank_debit_card",
            "display_order": 70,
            "aliases": ["paypal main", "paypal debit", "paypal bank", "paypal card", "paypal linked card"],
            "legacy": {"migration_rule": "H.paypal_via_main_bank"},
        })

    known_payment_account_keys = {
        "main_bank", "cash_flow", "pre_paid_card", "edenred", "paypal", "credit_card", "other_account"
    }
    for account in accounts:
        key = str(account.get("key") or account.get("id") or "")
        if not key or key in known_payment_account_keys or account.get("is_container"):
            continue
        account_kind = clean_text(account.get("account_kind") or account.get("type") or "")
        if account_kind in {"cash", "prepaid_balance", "wallet_balance", "dependent_wallet", "meal_voucher", "investment_cash", "other"}:
            method_type = {
                "cash": "cash",
                "prepaid_balance": "prepaid_card",
                "meal_voucher": "meal_voucher",
                "investment_cash": "investment_cash_transfer",
            }.get(account_kind, "wallet_balance")
            add({
                "id": key,
                "name": account.get("label") or account.get("name") or key.replace("_", " ").title(),
                "method_type": method_type,
                "settlement_mode": "stored_balance",
                "linked_account_id": key,
                "funding_account_id": key,
                "settlement_account_id": key,
                "display_order": int(account.get("display_order") or 1000),
                "aliases": account.get("aliases", []),
                "legacy": {"migration_rule": "generic_stored_balance"},
            })

    payload = {"schema_version": 1, "payment_methods": methods, "updated_at": utc_now()}
    return normalize_payment_methods_config(payload, accounts_payload=accounts_payload)




def ensure_methods_for_accounts(payload: Mapping[str, Any], accounts_payload: Mapping[str, Any]) -> dict[str, Any]:
    """Ensure every independent current/CashFlow account has at least one usable method.

    v17 created methods only when payment_methods.json was missing.  After users add
    Bank2, Revolut, CashFlow, etc., the UI needs those accounts to immediately
    appear in payment dropdowns and account cards.
    """
    result = deepcopy(dict(payload or {}))
    methods = [dict(method) for method in result.get("payment_methods", []) if isinstance(method, Mapping)]
    existing_ids = {str(method.get("id") or "") for method in methods}
    accounts = [dict(account) for account in accounts_payload.get("accounts", []) if isinstance(account, Mapping)]

    def _add(raw: Mapping[str, Any]) -> None:
        method = _normalize_payment_method_record(raw, index=len(methods))
        if method.get("id") and method.get("id") not in existing_ids:
            methods.append(method)
            existing_ids.add(str(method.get("id")))

    def _method_touches_account(method: Mapping[str, Any], key: str) -> bool:
        return key in {
            str(method.get("linked_account_id") or ""),
            str(method.get("funding_account_id") or ""),
            str(method.get("settlement_account_id") or ""),
        }

    def _has_active_method(key: str, method_type: str) -> bool:
        for method in methods:
            if method.get("is_archived") or not method.get("is_active", True):
                continue
            if clean_text(method.get("method_type") or "") == method_type and _method_touches_account(method, key):
                return True
        return False

    def _first_active_method_id_for_account(key: str, method_types: set[str]) -> str:
        for method in methods:
            if method.get("is_archived") or not method.get("is_active", True):
                continue
            method_type = clean_text(method.get("method_type") or "")
            if method_type in method_types and _method_touches_account(method, key):
                return str(method.get("id") or "")
        return ""

    def _merge_aliases(method: dict[str, Any], aliases: Iterable[str]) -> None:
        merged = split_aliases([*method.get("aliases", []), *aliases])
        method["aliases"] = merged

    def _unique_method_id(base: str) -> str:
        if base not in existing_ids:
            return base
        index = 2
        while f"{base}_{index}" in existing_ids:
            index += 1
        return f"{base}_{index}"

    for account in accounts:
        key = str(account.get("key") or account.get("id") or "")
        if not key or account.get("is_container") or account.get("is_liability") or not account.get("is_active", True):
            continue
        kind = clean_text(account.get("account_kind") or account.get("type") or "")
        label = account.get("label") or account.get("name") or key.replace("_", " ").title()
        order = int(_safe_number(account.get("display_order"), 1000))
        if kind == "current_account":
            if not _has_active_method(key, "debit_card"):
                _add({
                    "id": _unique_method_id(f"{key}_debit_card"),
                    "name": "Debit Card" if key == "main_bank" else f"{label} debit card",
                    "method_type": "debit_card",
                    "settlement_mode": "immediate",
                    "linked_account_id": key,
                    "funding_account_id": key,
                    "settlement_account_id": key,
                    "display_order": order,
                    "aliases": [key, label, f"{label} debit", f"{label} debit card", f"{label} card"],
                    "legacy": {"migration_rule": "auto_current_account_debit_card"},
                    "metadata": {"auto_default": True, "visible_card": True},
                })
            if not _has_active_method(key, "bank_transfer"):
                _add({
                    "id": _unique_method_id(f"{key}_transfer"),
                    "name": f"{label} transfer",
                    "method_type": "bank_transfer",
                    "settlement_mode": "immediate",
                    "linked_account_id": key,
                    "funding_account_id": key,
                    "settlement_account_id": key,
                    "display_order": order + 1,
                    "aliases": [key, label, f"{label} bank transfer", f"{label} bonifico"],
                    "legacy": {"migration_rule": "auto_current_account_bank_transfer"},
                    "metadata": {"auto_default": True, "visible_card": False},
                })
        elif kind in {"cash", "investment_cash"} or key in {"cash_flow", "cashflow", "cash"}:
            _add({
                "id": key,
                "name": label,
                "method_type": "cash" if kind == "cash" else "investment_cash_transfer",
                "settlement_mode": "stored_balance",
                "linked_account_id": key,
                "funding_account_id": key,
                "settlement_account_id": key,
                "display_order": order,
                "aliases": account.get("aliases", []) or [key, label],
                "legacy": {"migration_rule": "auto_cashflow_method"},
            })
        elif key != "paypal" and kind in {"wallet_balance", "dependent_wallet", "prepaid_balance", "meal_voucher"}:
            method_type = {"prepaid_balance": "prepaid_card", "meal_voucher": "meal_voucher"}.get(kind, "wallet_balance")
            _add({
                "id": key,
                "name": f"{label} balance",
                "method_type": method_type,
                "settlement_mode": "stored_balance",
                "linked_account_id": key,
                "funding_account_id": key,
                "settlement_account_id": key,
                "display_order": order,
                "aliases": account.get("aliases", []) or [key, label],
                "legacy": {"migration_rule": "auto_wallet_balance_method"},
            })

    account_keys = {str(account.get("key") or account.get("id") or "") for account in accounts}
    if "paypal" in account_keys:
        _add({
            "id": "paypal_balance",
            "name": "PayPal balance",
            "method_type": "wallet_balance",
            "settlement_mode": "stored_balance",
            "linked_account_id": "paypal",
            "funding_account_id": "paypal",
            "settlement_account_id": "paypal",
            "display_order": 40,
            "aliases": ["paypal", "pay pal", "paypal balance", "paypal wallet"],
            "legacy": {"migration_rule": "auto_paypal_balance_method"},
            "metadata": {"auto_default": True, "visible_card": False},
        })

    if "paypal" in account_keys and "main_bank" in account_keys:
        main_delegate = (
            _first_active_method_id_for_account("main_bank", {"debit_card"})
            or _first_active_method_id_for_account("main_bank", {"bank_transfer"})
            or "main_bank_debit_card"
        )
        _add({
            "id": "paypal_via_main_bank",
            "name": "PayPal via Main Bank card",
            "method_type": "wallet_linked_card",
            "settlement_mode": "delegated",
            "linked_account_id": "paypal",
            "delegates_to_payment_method_id": main_delegate,
            "display_order": 70,
            "aliases": ["paypal main", "paypal debit", "paypal bank", "paypal card", "paypal linked card"],
            "legacy": {"migration_rule": "auto_paypal_via_main_bank"},
            "metadata": {"auto_default": True, "visible_card": True},
        })

        for method in methods:
            if str(method.get("id") or "") != "paypal_via_main_bank":
                continue
            changed = False
            if clean_text(method.get("name") or "") in {"paypal via main bank", "paypal via main bank card"}:
                method["name"] = "PayPal via Main Bank card"
            if method.get("method_type") != "wallet_linked_card":
                method["method_type"] = "wallet_linked_card"
                changed = True
            if method.get("settlement_mode") != "delegated":
                method["settlement_mode"] = "delegated"
                changed = True
            if method.get("linked_account_id") != "paypal":
                method["linked_account_id"] = "paypal"
                changed = True
            current_delegate = str(method.get("delegates_to_payment_method_id") or "")
            if current_delegate in {"", "main_bank_transfer"} and main_delegate:
                method["delegates_to_payment_method_id"] = main_delegate
                changed = True
            before_aliases = list(method.get("aliases", []))
            _merge_aliases(method, ["paypal main", "paypal debit", "paypal bank", "paypal card", "paypal linked card"])
            if before_aliases != method.get("aliases", []):
                changed = True
            if changed:
                method["updated_at"] = utc_now()
            break

    result["payment_methods"] = methods
    result["updated_at"] = clean_label(result.get("updated_at") or "")
    return normalize_payment_methods_config(result, accounts_payload=accounts_payload)


def _is_legacy_default_credit_method(method: Mapping[str, Any]) -> bool:
    method_id = str(method.get("id") or "")
    legacy = method.get("legacy") if isinstance(method.get("legacy"), Mapping) else {}
    metadata = method.get("metadata") if isinstance(method.get("metadata"), Mapping) else {}
    if metadata.get("user_created") or metadata.get("manual_card"):
        return False
    return (
        method_id == "credit_card"
        and str(method.get("method_type") or "") == "credit_card"
        and str(legacy.get("migration_rule") or "") in {"", "F.credit_card"}
    )


def normalize_payment_methods_config(
    payload: Mapping[str, Any] | list[Mapping[str, Any]] | None,
    *,
    accounts_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if isinstance(payload, list):
        incoming: Mapping[str, Any] = {"payment_methods": payload}
    elif isinstance(payload, Mapping):
        incoming = payload
    else:
        incoming = {}

    records = incoming.get("payment_methods", [])
    if not isinstance(records, list) or not records:
        records = deepcopy(DEFAULT_PAYMENT_METHODS.get("payment_methods", []))

    methods: list[dict[str, Any]] = []
    active_ids: set[str] = set()
    active_names: set[str] = set()
    for index, raw in enumerate(records):
        if not isinstance(raw, Mapping):
            continue
        method = _normalize_payment_method_record(raw, index=index)
        if _is_legacy_default_credit_method(method):
            method["is_active"] = False
            method["is_archived"] = True
            method["archived_at"] = method.get("archived_at") or utc_now()
            method.setdefault("legacy", {})["auto_archived_reason"] = "default_credit_card_removed_from_new_account_model"
        method_id = str(method.get("id") or "")
        name_key = clean_text(method.get("name") or "")
        active = bool(method.get("is_active", True)) and not bool(method.get("is_archived", False))
        if active and (method_id in active_ids or name_key in active_names):
            method["is_active"] = False
            method["is_archived"] = True
            method["archived_at"] = method.get("archived_at") or utc_now()
            method.setdefault("legacy", {})["auto_archived_reason"] = "duplicate_active_payment_method"
        if bool(method.get("is_active", True)) and not bool(method.get("is_archived", False)):
            active_ids.add(method_id)
            active_names.add(name_key)
        methods.append(method)

    accounts_payload = accounts_payload or {"accounts": []}
    for index, method in enumerate(methods):
        errors = validate_payment_method(method, accounts_payload, methods)
        if errors:
            method["validation_errors"] = errors
        else:
            method.pop("validation_errors", None)

    methods.sort(key=lambda item: (_display_order_for_sort(item.get("display_order")), str(item.get("name") or "")))
    result = {"schema_version": 1, "payment_methods": methods, "updated_at": clean_label(incoming.get("updated_at") or "")}
    for key, value in incoming.items():
        if key not in result:
            result[key] = deepcopy(value)
    return result


def write_account_payment_migration_report(
    user_id: str | None,
    *,
    from_accounts_schema: int | None,
    payment_methods_created: bool,
    notes: list[str] | None = None,
) -> None:
    try:
        user_dir = get_user_data_dir(user_id)
    except RuntimeError:
        return
    path = user_dir / "migration_info.json"
    payload = read_json(path, {})
    if not isinstance(payload, dict):
        payload = {"schema_version": 1}
    payload["account_payment_model_migration"] = {
        "from_accounts_schema": from_accounts_schema,
        "to_accounts_schema": 3,
        "payment_methods_created": bool(payment_methods_created),
        "created_at": utc_now(),
        "notes": notes or [],
    }
    write_json_atomic(path, payload)


def _method_from_form(form: Mapping[str, Any], *, method_id: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    card_payload = {
        "network": clean_label(form.get("card_network") or form.get("network") or ""),
        "last4": clean_label(form.get("card_last4") or form.get("last4") or ""),
        "holder_name": clean_label(form.get("card_holder_name") or form.get("holder_name") or ""),
        "expiry_month": clean_label(form.get("card_expiry_month") or form.get("expiry_month") or ""),
        "expiry_year": clean_label(form.get("card_expiry_year") or form.get("expiry_year") or ""),
    }
    if any(card_payload.values()):
        metadata["card"] = card_payload
        metadata["manual_card"] = True
        metadata["visible_card"] = True
        metadata["user_created"] = True

    return {
        "id": method_id,
        "name": clean_label(form.get("name") or method_id.replace("_", " ").title()),
        "method_type": clean_text(form.get("method_type") or "other"),
        "linked_account_id": clean_text(form.get("linked_account_id") or ""),
        "funding_account_id": clean_text(form.get("funding_account_id") or ""),
        "settlement_account_id": clean_text(form.get("settlement_account_id") or ""),
        "liability_account_id": clean_text(form.get("liability_account_id") or ""),
        "settlement_mode": clean_text(form.get("settlement_mode") or "external_record_only"),
        "delegates_to_payment_method_id": clean_text(form.get("delegates_to_payment_method_id") or ""),
        "is_default": str(form.get("is_default", "")).lower() in {"1", "true", "on", "yes"},
        "is_active": str(form.get("is_active", "1")).lower() not in {"0", "false", "off", "no"},
        "is_archived": str(form.get("is_archived", "")).lower() in {"1", "true", "on", "yes"},
        "display_order": form.get("display_order") or 1000,
        "rules": {
            "due_day": _parse_optional_day(form.get("due_day")),
            "statement_day": _parse_optional_day(form.get("statement_day")),
            "settlement_day_policy": clean_text(form.get("settlement_day_policy") or "next_month"),
            "allow_manual_due_date": str(form.get("allow_manual_due_date", "1")).lower() not in {"0", "false", "off", "no"},
        },
        "aliases": split_aliases(form.get("aliases")),
        "metadata": metadata,
    }


def _normalize_payment_method_record(raw: Mapping[str, Any], *, index: int = 0) -> dict[str, Any]:
    method_id = slugify(raw.get("id") or raw.get("key") or raw.get("name"))
    name = clean_label(raw.get("name") or raw.get("label") or method_id.replace("_", " ").title())
    method_type = clean_text(raw.get("method_type") or raw.get("type") or "other")
    if method_type not in METHOD_TYPES:
        method_type = "other"
    settlement_mode = clean_text(raw.get("settlement_mode") or "external_record_only")
    if settlement_mode not in SETTLEMENT_MODES:
        settlement_mode = "external_record_only"
    rules = raw.get("rules") if isinstance(raw.get("rules"), Mapping) else {}
    aliases = split_aliases(raw.get("aliases"))
    for value in (method_id, name):
        alias = clean_text(value)
        if alias and alias not in aliases:
            aliases.append(alias)
    archived_at = clean_label(raw.get("archived_at") or "")
    is_archived = bool(raw.get("is_archived", False)) or bool(archived_at)
    return {
        "id": method_id,
        "name": name,
        "method_type": method_type,
        "linked_account_id": clean_text(raw.get("linked_account_id") or ""),
        "funding_account_id": clean_text(raw.get("funding_account_id") or ""),
        "settlement_account_id": clean_text(raw.get("settlement_account_id") or ""),
        "liability_account_id": clean_text(raw.get("liability_account_id") or ""),
        "settlement_mode": settlement_mode,
        "delegates_to_payment_method_id": clean_text(raw.get("delegates_to_payment_method_id") or ""),
        "is_default": bool(raw.get("is_default", False)),
        "is_active": bool(raw.get("is_active", True)) and not is_archived,
        "is_archived": is_archived,
        "display_order": int(_safe_number(raw.get("display_order"), (index + 1) * 10)),
        "rules": {
            "due_day": _parse_optional_day(rules.get("due_day")),
            "statement_day": _parse_optional_day(rules.get("statement_day")),
            "settlement_day_policy": clean_text(rules.get("settlement_day_policy") or "next_month") or "next_month",
            "allow_manual_due_date": bool(rules.get("allow_manual_due_date", True)),
        },
        "aliases": aliases,
        "legacy": deepcopy(raw.get("legacy") if isinstance(raw.get("legacy"), dict) else {}),
        "metadata": deepcopy(raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}),
        "created_at": clean_label(raw.get("created_at") or ""),
        "updated_at": clean_label(raw.get("updated_at") or ""),
        "archived_at": archived_at,
    }


def _set_method_archived(method_id: str, *, archived: bool, user_id: str | None = None) -> bool:
    payload = ensure_payment_methods_file(user_id=user_id)
    wanted = normalize_payment_method_id(method_id, user_id=user_id)
    changed = False
    for method in payload.get("payment_methods", []):
        if method.get("id") != wanted:
            continue
        method["is_archived"] = archived
        method["is_active"] = not archived
        method["archived_at"] = utc_now() if archived else ""
        method["updated_at"] = utc_now()
        changed = True
        break
    if changed:
        save_payment_methods(payload, user_id=user_id)
    return changed


def _account_ids(accounts: Mapping[str, Any] | list[Mapping[str, Any]]) -> set[str]:
    if isinstance(accounts, Mapping):
        rows = accounts.get("accounts", [])
    else:
        rows = accounts
    result: set[str] = set()
    for account in rows if isinstance(rows, list) else []:
        if not isinstance(account, Mapping):
            continue
        for key in [account.get("id"), account.get("key")]:
            value = str(key or "")
            if value:
                result.add(value)
    return result


def _method_ids(methods: Mapping[str, Any] | list[Mapping[str, Any]]) -> set[str]:
    if isinstance(methods, Mapping):
        rows = methods.get("payment_methods", [])
    else:
        rows = methods
    return {str(method.get("id") or "") for method in rows if isinstance(method, Mapping) and method.get("id")}


def _delegation_has_cycle(start_id: str, delegate_id: str, methods: Mapping[str, Any] | list[Mapping[str, Any]]) -> bool:
    if isinstance(methods, Mapping):
        rows = methods.get("payment_methods", [])
    else:
        rows = methods
    by_id = {str(method.get("id") or ""): method for method in rows if isinstance(method, Mapping)}
    seen = {start_id}
    current = delegate_id
    while current:
        if current in seen:
            return True
        seen.add(current)
        current = str(by_id.get(current, {}).get("delegates_to_payment_method_id") or "")
    return False



def _display_order_for_sort(value: Any) -> int:
    try:
        return int(float(str(value).replace(",", ".")))
    except (TypeError, ValueError):
        return 1000


def _safe_number(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return default


def set_default_payment_method(method_id: str, user_id: str | None = None) -> bool:
    payload = ensure_payment_methods_file(user_id=user_id)
    wanted = normalize_payment_method_id(method_id, user_id=user_id)
    matched = False
    for method in payload.get("payment_methods", []):
        if method.get("id") == wanted and method.get("is_active", True) and not method.get("is_archived", False):
            method["is_default"] = True
            method["updated_at"] = utc_now()
            matched = True
        elif method.get("is_default"):
            method["is_default"] = False
            method["updated_at"] = utc_now()
    if matched:
        save_payment_methods(payload, user_id=user_id)
    return matched
