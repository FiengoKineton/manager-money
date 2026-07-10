from __future__ import annotations

import re
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


def _clear_payment_method_lookup_cache() -> None:
    try:
        from money_manager.cache import request_cache

        request_cache.delete_prefix("payment_method_lookup:")
    except Exception:
        pass


def save_payment_methods(payload: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    from money_manager.services.account_config_service import load_accounts_config

    accounts_payload = load_accounts_config(user_id=user_id)
    normalized = normalize_payment_methods_config(payload, accounts_payload=accounts_payload)
    normalized["updated_at"] = utc_now()
    _clear_payment_method_lookup_cache()
    saved = save_user_config(PAYMENT_METHODS_FILE, normalized, user_id=user_id)
    _clear_payment_method_lookup_cache()
    return saved


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
    if created or normalized_with_account_methods != raw:
        _clear_payment_method_lookup_cache()
        save_user_config(PAYMENT_METHODS_FILE, normalized_with_account_methods, user_id=user_id)
        _clear_payment_method_lookup_cache()
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
            str(method.get("liability_account_id") or ""),
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

    def _method_by_id(method_id: str) -> dict[str, Any] | None:
        wanted = str(method_id or "")
        for method in methods:
            if str(method.get("id") or "") == wanted:
                return method
        return None

    def _is_active_method(method: Mapping[str, Any] | None) -> bool:
        return bool(method) and bool(method.get("is_active", True)) and not bool(method.get("is_archived", False))

    accounts_by_key: dict[str, dict[str, Any]] = {
        str(account.get("key") or account.get("id") or ""): account
        for account in accounts
        if str(account.get("key") or account.get("id") or "")
    }

    def _account_key(account: Mapping[str, Any] | None) -> str:
        return str((account or {}).get("key") or (account or {}).get("id") or "")

    def _account_parent_for_key(key: str) -> str:
        account = accounts_by_key.get(str(key or ""))
        if not account:
            return ""
        return str(account.get("parent_account_id") or account.get("parent_key") or "")

    def _account_kind_for_key(key: str) -> str:
        account = accounts_by_key.get(str(key or ""))
        return clean_text((account or {}).get("account_kind") or (account or {}).get("type") or "")

    def _account_is_active(key: str) -> bool:
        account = accounts_by_key.get(str(key or ""))
        if not account:
            return False
        return bool(account.get("is_active", True)) and not bool(account.get("is_archived")) and not bool(account.get("is_closed"))

    def _current_account_keys() -> list[str]:
        result_keys: list[str] = []
        for account in accounts:
            key = _account_key(account)
            if not key or not _account_is_active(key):
                continue
            if _account_kind_for_key(key) == "current_account" or bool(account.get("is_current_account")):
                result_keys.append(key)
        if "main_bank" in result_keys:
            result_keys.remove("main_bank")
            result_keys.insert(0, "main_bank")
        return result_keys

    def _parent_for_credit_method(method: Mapping[str, Any]) -> str:
        liability_key = str(method.get("liability_account_id") or "")
        liability_parent = _account_parent_for_key(liability_key) if liability_key else ""
        if liability_parent:
            return liability_parent
        for field in ("linked_account_id", "funding_account_id", "settlement_account_id", "parent_account_id"):
            ref = str(method.get(field) or "")
            if not ref or not _account_is_active(ref):
                continue
            if _account_kind_for_key(ref) == "current_account":
                return ref
            parent = _account_parent_for_key(ref)
            if parent and _account_is_active(parent):
                return parent
        return (_current_account_keys() or ["main_bank"])[0]

    def _ensure_credit_liability_account(parent_key: str, card_name: str = "Credit card") -> str:
        parent_key = parent_key if _account_is_active(parent_key) else ((_current_account_keys() or ["main_bank"])[0])
        for account in accounts:
            key = _account_key(account)
            if not key or not _account_is_active(key):
                continue
            if _account_kind_for_key(key) == "credit_card_liability" and _account_parent_for_key(key) == parent_key:
                return key
        try:
            from money_manager.services.account_service import ensure_credit_card_liability_account
            from money_manager.services.account_config_service import account_by_key

            key = ensure_credit_card_liability_account(parent_key, card_name or "Credit card")
            account = account_by_key(key, include_archived=True) or {}
            if account:
                account_key = _account_key(account)
                if account_key and account_key not in accounts_by_key:
                    account_row = dict(account)
                    accounts.append(account_row)
                    accounts_by_key[account_key] = account_row
            return str(key or "")
        except Exception:
            return ""

    def _is_credit_like_method(method: Mapping[str, Any]) -> bool:
        if clean_text(method.get("method_type") or "") == "credit_card":
            return True
        if clean_text(method.get("settlement_mode") or "") == "delayed":
            return True
        if str(method.get("liability_account_id") or ""):
            return True
        # Some legacy rows were accidentally saved as debit/other methods while
        # all their routes pointed at the credit-liability bucket. Repair those
        # rows as credit cards so they stop appearing as hundreds of methods on
        # the liability account.
        for field in ("linked_account_id", "funding_account_id", "settlement_account_id"):
            ref = str(method.get(field) or "")
            if ref and _account_kind_for_key(ref) == "credit_card_liability":
                return True
        return False

    def _credit_method_has_required_accounts(method: Mapping[str, Any], parent_key: str = "") -> bool:
        liability = str(method.get("liability_account_id") or "")
        settlement = str(method.get("settlement_account_id") or method.get("funding_account_id") or "")
        if not liability or not settlement:
            return False
        if not _account_is_active(liability) or not _account_is_active(settlement):
            return False
        if parent_key:
            refs = {
                str(method.get("linked_account_id") or ""),
                str(method.get("funding_account_id") or ""),
                str(method.get("settlement_account_id") or ""),
                _account_parent_for_key(liability),
            }
            if parent_key not in refs:
                return False
        return True

    def _active_credit_method_ids(parent_key: str = "") -> list[str]:
        result_ids: list[str] = []
        for method in methods:
            if not _is_active_method(method) or not _is_credit_like_method(method):
                continue
            method_id = str(method.get("id") or "")
            # The old built-in `credit_card` placeholder is intentionally not used
            # as a PayPal delegate; it was often a missing liability bucket.  A
            # real repaired/user card gets its own stable id below.
            if method_id == "credit_card" and _is_legacy_default_credit_method(method):
                continue
            if not _credit_method_has_required_accounts(method, parent_key):
                continue
            result_ids.append(method_id)
        return result_ids

    def _first_active_credit_method_id(parent_key: str = "") -> str:
        ids = _active_credit_method_ids(parent_key) or _active_credit_method_ids("")
        return ids[0] if ids else ""

    def _materialize_legacy_account_cards(account: Mapping[str, Any]) -> None:
        """Expose cards saved only on accounts.json as real payment methods.

        Older screens stored card details under the Conto's ``cards`` list.  The
        transaction form reads payment_methods.json, so those cards existed in
        the account modal but were not selectable for payments or credit
        settlements.
        """
        parent_key = _account_key(account)
        if not parent_key or not _account_is_active(parent_key):
            return
        cards = account.get("cards") if isinstance(account.get("cards"), list) else []
        if not cards:
            return

        def _card_clean(value: Any) -> str:
            return clean_label(value)

        def _method_belongs_to_parent(method: Mapping[str, Any]) -> bool:
            direct_refs = {
                str(method.get("linked_account_id") or ""),
                str(method.get("funding_account_id") or ""),
                str(method.get("settlement_account_id") or ""),
                str(method.get("parent_account_id") or ""),
            }
            if parent_key in direct_refs:
                return True
            for ref in [*direct_refs, str(method.get("liability_account_id") or "")]:
                if ref and _account_parent_for_key(ref) == parent_key:
                    return True
            return False

        def _method_exists_for_card(card: Mapping[str, Any], label: str, method_type: str) -> bool:
            card_id = _card_clean(card.get("id"))
            last4 = _card_clean(card.get("last4") or card.get("card_last4"))
            label_key = clean_text(label)
            for method in methods:
                if method.get("is_archived") or not method.get("is_active", True):
                    continue
                if clean_text(method.get("method_type") or "") != method_type:
                    continue
                if not _method_belongs_to_parent(method):
                    continue
                metadata = method.get("metadata") if isinstance(method.get("metadata"), Mapping) else {}
                card_meta = metadata.get("card") if isinstance(metadata.get("card"), Mapping) else {}
                if card_id and str(metadata.get("legacy_account_card_id") or "") == card_id:
                    return True
                if last4 and clean_text(card_meta.get("last4")) == clean_text(last4):
                    return True
                if label_key and clean_text(method.get("name") or "") == label_key:
                    return True
            return False

        for card in cards:
            if not isinstance(card, Mapping):
                continue
            if card.get("is_archived") or card.get("is_active", True) is False:
                continue
            raw_type = clean_text(card.get("method_type") or card.get("card_type") or card.get("type") or "debit")
            method_type = {
                "debit": "debit_card",
                "debit_card": "debit_card",
                "credit": "credit_card",
                "credit_card": "credit_card",
                "prepaid": "prepaid_card",
                "prepaid_card": "prepaid_card",
            }.get(raw_type, "debit_card")
            label = _card_clean(card.get("label") or card.get("name") or card.get("card_label")) or {
                "debit_card": "Debit Card",
                "credit_card": "Credit Card",
                "prepaid_card": "Prepaid Card",
            }.get(method_type, "Card")
            if _method_exists_for_card(card, label, method_type):
                continue

            card_key = parent_key
            liability_key = ""
            settlement_mode = "immediate"
            if method_type == "credit_card":
                settlement_mode = "delayed"
                liability_key = _ensure_credit_liability_account(parent_key, label)
            elif method_type == "prepaid_card":
                settlement_mode = "stored_balance"
                try:
                    from money_manager.services.account_service import ensure_prepaid_card_balance_account

                    card_key = ensure_prepaid_card_balance_account(parent_key, label) or parent_key
                except Exception:
                    card_key = parent_key

            raw_method = {
                "id": _unique_method_id(f"{parent_key}_{method_type}_{slugify(label)}"),
                "name": label,
                "method_type": method_type,
                "settlement_mode": settlement_mode,
                "linked_account_id": parent_key if method_type == "credit_card" else card_key,
                "funding_account_id": parent_key if method_type == "credit_card" else card_key,
                "settlement_account_id": parent_key if method_type == "credit_card" else card_key,
                "liability_account_id": liability_key,
                "parent_account_id": parent_key,
                "display_order": int(_safe_number(account.get("display_order"), 1000)) + (60 if method_type == "credit_card" else 2),
                "rules": {"due_day": _parse_optional_day(card.get("due_day")) or 15, "statement_day": _parse_optional_day(card.get("statement_day")), "settlement_day_policy": "next_month", "allow_manual_due_date": True},
                "aliases": split_aliases([label, card.get("last4") or "", *(card.get("aliases", []) if isinstance(card.get("aliases"), list) else [])]),
                "legacy": {"migration_rule": "materialized_from_account_card"},
                "metadata": {
                    "visible_card": True,
                    "manual_card": True,
                    "user_created": True,
                    "legacy_account_card_id": _card_clean(card.get("id")),
                    "card": {
                        "network": _card_clean(card.get("network") or card.get("card_network")),
                        "last4": _card_clean(card.get("last4") or card.get("card_last4")),
                        "holder_name": _card_clean(card.get("holder_name") or card.get("card_holder_name")),
                        "expiry_month": _card_clean(card.get("expiry_month") or card.get("card_expiry_month")),
                        "expiry_year": _card_clean(card.get("expiry_year") or card.get("card_expiry_year")),
                    },
                },
            }
            if method_type != "credit_card":
                raw_method["rules"] = {"due_day": None, "statement_day": None, "settlement_day_policy": "next_month", "allow_manual_due_date": True}
            _add(raw_method)

    def _parent_for_prepaid_method(method: Mapping[str, Any]) -> str:
        explicit_parent = str(method.get("parent_account_id") or "")
        if explicit_parent and _account_is_active(explicit_parent):
            return explicit_parent
        for field in ("linked_account_id", "funding_account_id", "settlement_account_id"):
            ref = str(method.get(field) or "")
            if not ref:
                continue
            parent = _account_parent_for_key(ref)
            if parent and _account_is_active(parent):
                return parent
            if _account_is_active(ref) and _account_kind_for_key(ref) == "current_account":
                return ref
        return (_current_account_keys() or ["main_bank"])[0]

    def _repair_prepaid_method_accounts() -> None:
        """Reconnect active prepaid cards to one accessible stored-balance child.

        Older repair passes could leave the card pointing directly at Main or
        without a parent. That both hid the prepaid balance and caused the legacy
        account-card materializer to create another method on every read.
        """
        for method in methods:
            if not _is_active_method(method):
                continue
            if clean_text(method.get("method_type") or "") != "prepaid_card":
                continue
            parent_key = _parent_for_prepaid_method(method)
            card_name = clean_label(method.get("name") or "Prepaid card") or "Prepaid card"
            balance_key = ""
            for field in ("linked_account_id", "funding_account_id", "settlement_account_id"):
                ref = str(method.get(field) or "")
                if ref and _account_is_active(ref) and _account_kind_for_key(ref) == "prepaid_balance":
                    balance_key = ref
                    break
            try:
                from money_manager.services.account_service import ensure_prepaid_card_balance_account
                from money_manager.services.account_config_service import account_by_key

                balance_key = ensure_prepaid_card_balance_account(parent_key, card_name) or balance_key
                account = account_by_key(balance_key, include_archived=True) or {}
                account_key = _account_key(account)
                if account_key and account_key not in accounts_by_key:
                    account_row = dict(account)
                    accounts.append(account_row)
                    accounts_by_key[account_key] = account_row
            except Exception:
                pass
            if not balance_key:
                continue
            changed = False
            for field in ("linked_account_id", "funding_account_id", "settlement_account_id"):
                if str(method.get(field) or "") != balance_key:
                    method[field] = balance_key
                    changed = True
            if str(method.get("parent_account_id") or "") != parent_key:
                method["parent_account_id"] = parent_key
                changed = True
            if clean_text(method.get("settlement_mode") or "") != "stored_balance":
                method["settlement_mode"] = "stored_balance"
                changed = True
            metadata = dict(method.get("metadata") if isinstance(method.get("metadata"), Mapping) else {})
            if metadata.get("visible_card") is not True:
                metadata["visible_card"] = True
                changed = True
            if metadata != method.get("metadata"):
                method["metadata"] = metadata
            if changed:
                method["updated_at"] = utc_now()

    def _generated_card_signature(method: Mapping[str, Any]) -> tuple[str, ...] | None:
        method_type = clean_text(method.get("method_type") or "")
        if method_type not in {"debit_card", "credit_card", "prepaid_card", "wallet_linked_card"}:
            return None
        metadata = method.get("metadata") if isinstance(method.get("metadata"), Mapping) else {}
        legacy = method.get("legacy") if isinstance(method.get("legacy"), Mapping) else {}
        migration_rule = clean_text(legacy.get("migration_rule") or "")
        source_card_id = clean_text(metadata.get("legacy_account_card_id") or "")
        generated = bool(
            source_card_id
            or metadata.get("auto_default")
            or migration_rule in {
                "materialized_from_account_card",
                "auto_current_account_debit_card",
                "auto_credit_card_delegate_repair",
                "auto_paypal_via_credit_card",
                "auto_paypal_via_main_bank",
            }
        )
        if not generated:
            return None
        parent = str(method.get("parent_account_id") or "")
        if not parent:
            parent = _parent_for_prepaid_method(method) if method_type == "prepaid_card" else _parent_for_credit_method(method)
        card_meta = metadata.get("card") if isinstance(metadata.get("card"), Mapping) else {}
        last4 = clean_text(card_meta.get("last4") or method.get("last4") or "")
        name = clean_text(method.get("name") or method_type)
        if source_card_id:
            return ("source-card", parent, method_type, source_card_id)
        if method_type == "wallet_linked_card":
            return ("generated-card", parent, method_type, str(method.get("id") or ""), name)
        return (
            "generated-card",
            parent,
            method_type,
            name,
            last4,
            str(method.get("linked_account_id") or ""),
            str(method.get("liability_account_id") or ""),
        )

    def _generated_card_score(method: Mapping[str, Any]) -> tuple[int, int, int, int]:
        metadata = method.get("metadata") if isinstance(method.get("metadata"), Mapping) else {}
        card_meta = metadata.get("card") if isinstance(metadata.get("card"), Mapping) else {}
        method_id = str(method.get("id") or "")
        return (
            1 if clean_text(card_meta.get("last4") or "") else 0,
            1 if clean_text(method.get("created_at") or "") else 0,
            1 if not re.search(r"_\d+$", method_id) else 0,
            -len(method_id),
        )

    def _deduplicate_generated_card_methods() -> dict[str, str]:
        """Archive only provably generated duplicate cards.

        User-created cards with distinct ids remain separate even when they share
        a display name and have no last four digits. The cleanup targets legacy
        materialization/auto-default clones, which are the source of card counts
        growing into the hundreds while only a few real cards are visible.
        """
        groups: dict[tuple[str, ...], list[dict[str, Any]]] = {}
        for method in methods:
            if not _is_active_method(method):
                continue
            signature = _generated_card_signature(method)
            if signature:
                groups.setdefault(signature, []).append(method)

        redirects: dict[str, str] = {}
        for rows in groups.values():
            if len(rows) <= 1:
                continue
            survivor = sorted(rows, key=_generated_card_score, reverse=True)[0]
            survivor_id = str(survivor.get("id") or "")
            for duplicate in rows:
                duplicate_id = str(duplicate.get("id") or "")
                if duplicate is survivor or not duplicate_id:
                    continue
                _merge_aliases(survivor, [duplicate_id, duplicate.get("name") or "", *(duplicate.get("aliases") or [])])
                survivor_meta = dict(survivor.get("metadata") if isinstance(survivor.get("metadata"), Mapping) else {})
                duplicate_meta = duplicate.get("metadata") if isinstance(duplicate.get("metadata"), Mapping) else {}
                if not survivor_meta.get("card") and duplicate_meta.get("card"):
                    survivor_meta["card"] = deepcopy(duplicate_meta.get("card"))
                survivor["metadata"] = survivor_meta
                duplicate["is_active"] = False
                duplicate["is_archived"] = True
                duplicate["archived_at"] = duplicate.get("archived_at") or utc_now()
                duplicate["updated_at"] = utc_now()
                legacy = dict(duplicate.get("legacy") if isinstance(duplicate.get("legacy"), Mapping) else {})
                legacy["auto_archived_reason"] = "duplicate_generated_card_method"
                legacy["replacement_payment_method_id"] = survivor_id
                duplicate["legacy"] = legacy
                redirects[duplicate_id] = survivor_id
        if redirects:
            for method in methods:
                delegate_id = str(method.get("delegates_to_payment_method_id") or "")
                if delegate_id in redirects:
                    method["delegates_to_payment_method_id"] = redirects[delegate_id]
                    method["updated_at"] = utc_now()
        return redirects

    def _repair_credit_method_accounts() -> None:
        for method in methods:
            if not _is_credit_like_method(method):
                continue
            legacy_info = method.get("legacy") if isinstance(method.get("legacy"), Mapping) else {}
            if (method.get("is_archived") or not method.get("is_active", True)) and legacy_info.get("auto_archived_reason") == "duplicate_active_payment_method":
                # Older repair code archived cards just because another method had
                # the same display name.  Names are allowed to repeat; ids are the
                # stable identity.  Restore those accidentally hidden cards.
                method["is_active"] = True
                method["is_archived"] = False
                method["archived_at"] = ""
                method["updated_at"] = utc_now()
            if _is_legacy_default_credit_method(method):
                # Keep legacy placeholder archived.  If PayPal still points here,
                # a concrete replacement method is created by _ensure_default_credit_method().
                method["is_active"] = False
                method["is_archived"] = True
                method["archived_at"] = method.get("archived_at") or utc_now()
                continue
            if not _is_active_method(method):
                continue

            parent_key = _parent_for_credit_method(method)
            liability_key = str(method.get("liability_account_id") or "")
            changed = False
            if not liability_key or not _account_is_active(liability_key) or _account_kind_for_key(liability_key) != "credit_card_liability":
                liability_key = _ensure_credit_liability_account(parent_key, str(method.get("name") or "Credit card"))
                if liability_key:
                    method["liability_account_id"] = liability_key
                    changed = True

            liability_parent = _account_parent_for_key(liability_key) if liability_key else ""
            if liability_parent:
                parent_key = liability_parent

            if clean_text(method.get("method_type") or "") != "credit_card":
                method["method_type"] = "credit_card"
                changed = True
            if clean_text(method.get("settlement_mode") or "") != "delayed":
                method["settlement_mode"] = "delayed"
                changed = True
            for field in ("linked_account_id", "funding_account_id", "settlement_account_id"):
                ref = str(method.get(field) or "")
                if not ref or ref == liability_key or not _account_is_active(ref):
                    method[field] = parent_key
                    changed = True
            rules = dict(method.get("rules") if isinstance(method.get("rules"), Mapping) else {})
            if not _parse_optional_day(rules.get("due_day")):
                rules["due_day"] = 15
                changed = True
            if not clean_text(rules.get("settlement_day_policy") or ""):
                rules["settlement_day_policy"] = "next_month"
                changed = True
            if rules != method.get("rules"):
                method["rules"] = rules
            before_aliases = list(method.get("aliases", []))
            _merge_aliases(method, ["credit", "credit card", "carta credito", "carta di credito", str(method.get("name") or "")])
            if before_aliases != method.get("aliases", []):
                changed = True
            metadata = dict(method.get("metadata") if isinstance(method.get("metadata"), Mapping) else {})
            if metadata.get("visible_card") is not True:
                metadata["visible_card"] = True
                changed = True
            if metadata != method.get("metadata"):
                method["metadata"] = metadata
            if changed:
                method["updated_at"] = utc_now()

    def _ensure_default_credit_method(parent_key: str = "main_bank") -> str:
        existing = _first_active_credit_method_id(parent_key)
        if existing:
            return existing
        parent_key = parent_key if _account_is_active(parent_key) else ((_current_account_keys() or ["main_bank"])[0])
        liability_key = _ensure_credit_liability_account(parent_key, "Credit card")
        if not liability_key:
            return ""
        method_id = _unique_method_id(f"{parent_key}_credit_card")
        _add({
            "id": method_id,
            "name": "Credit Card" if parent_key == "main_bank" else f"{parent_key.replace('_', ' ').title()} credit card",
            "method_type": "credit_card",
            "settlement_mode": "delayed",
            "linked_account_id": parent_key,
            "funding_account_id": parent_key,
            "settlement_account_id": parent_key,
            "liability_account_id": liability_key,
            "display_order": 60,
            "rules": {"due_day": 15, "statement_day": None, "settlement_day_policy": "next_month", "allow_manual_due_date": True},
            "aliases": ["credit", "credit card", "main credit", "main credit card", "carta credito", "carta di credito"],
            "legacy": {"migration_rule": "auto_credit_card_delegate_repair"},
            "metadata": {"auto_default": True, "visible_card": True, "auto_repaired_credit_delegate": True},
        })
        return method_id

    def _credit_card_signature(method: Mapping[str, Any]) -> tuple[str, str, str]:
        metadata = method.get("metadata") if isinstance(method.get("metadata"), Mapping) else {}
        card_meta = metadata.get("card") if isinstance(metadata.get("card"), Mapping) else {}
        last4 = clean_text(card_meta.get("last4") or metadata.get("last4") or method.get("last4") or "")
        name = clean_text(method.get("name") or "Credit Card") or "credit card"
        parent = _parent_for_credit_method(method)
        if not parent:
            parent = "main_bank"
        # User-created cards are distinct stable objects even when the user has
        # not entered the last four digits yet. Older repair logic grouped every
        # manual card with the same generic name and silently archived all but
        # one, making multiple real cards look like a single reference.
        if not last4 and (metadata.get("user_created") or metadata.get("manual_card")):
            return (parent, f"{name}:{method.get('id') or ''}", "manual")
        return (parent, name, last4)

    def _credit_method_score(method: Mapping[str, Any]) -> tuple[int, int, int, int, int]:
        metadata = method.get("metadata") if isinstance(method.get("metadata"), Mapping) else {}
        card_meta = metadata.get("card") if isinstance(metadata.get("card"), Mapping) else {}
        legacy = method.get("legacy") if isinstance(method.get("legacy"), Mapping) else {}
        method_id = str(method.get("id") or "")
        has_last4 = 1 if clean_text(card_meta.get("last4") or method.get("last4") or "") else 0
        manual = 1 if metadata.get("user_created") or metadata.get("manual_card") else 0
        valid = 1 if _credit_method_has_required_accounts(method) else 0
        not_auto_repair = 0 if legacy.get("migration_rule") == "auto_credit_card_delegate_repair" else 1
        # Prefer stable non-suffixed ids over generated _2/_3/... ids.
        stable_id = 1 if not re.search(r"_\d+$", method_id) else 0
        return (valid, manual, has_last4, not_auto_repair, stable_id)

    def _merge_credit_method_fields(target: dict[str, Any], duplicate: Mapping[str, Any]) -> None:
        before_aliases = list(target.get("aliases", []))
        _merge_aliases(target, [*(duplicate.get("aliases") or []), duplicate.get("id") or "", duplicate.get("name") or ""])
        if before_aliases != target.get("aliases", []):
            target["updated_at"] = utc_now()
        target_meta = dict(target.get("metadata") if isinstance(target.get("metadata"), Mapping) else {})
        dup_meta = duplicate.get("metadata") if isinstance(duplicate.get("metadata"), Mapping) else {}
        target_card = dict(target_meta.get("card") if isinstance(target_meta.get("card"), Mapping) else {})
        dup_card = dup_meta.get("card") if isinstance(dup_meta.get("card"), Mapping) else {}
        for field in ["network", "last4", "holder_name", "expiry_month", "expiry_year"]:
            if not clean_label(target_card.get(field)) and clean_label((dup_card or {}).get(field)):
                target_card[field] = clean_label(dup_card.get(field))
        if target_card:
            target_meta["card"] = target_card
        if target_meta:
            target["metadata"] = target_meta

    def _deduplicate_credit_methods() -> dict[str, str]:
        """Archive duplicate credit-card payment methods and return id redirects.

        v10 could materialize/re-activate many identical account cards.  The
        payment-method id is still the durable identity, but the UI should show a
        single active card for one real card.  We keep the best candidate and map
        every archived duplicate to the survivor so delegated wrappers such as
        PayPal via Credit Card stay valid.
        """
        groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        for method in methods:
            if not _is_credit_like_method(method) or _is_legacy_default_credit_method(method):
                continue
            if not _is_active_method(method):
                continue
            groups.setdefault(_credit_card_signature(method), []).append(method)

        redirects: dict[str, str] = {}
        for rows in groups.values():
            if len(rows) <= 1:
                continue
            survivor = sorted(
                rows,
                key=lambda item: (_credit_method_score(item), -len(str(item.get("id") or ""))),
                reverse=True,
            )[0]
            survivor_id = str(survivor.get("id") or "")
            for duplicate in rows:
                duplicate_id = str(duplicate.get("id") or "")
                if not duplicate_id or duplicate is survivor:
                    continue
                _merge_credit_method_fields(survivor, duplicate)
                duplicate["is_active"] = False
                duplicate["is_archived"] = True
                duplicate["archived_at"] = duplicate.get("archived_at") or utc_now()
                duplicate["updated_at"] = utc_now()
                legacy = dict(duplicate.get("legacy") if isinstance(duplicate.get("legacy"), Mapping) else {})
                legacy["auto_archived_reason"] = "duplicate_credit_card_payment_method"
                legacy["replacement_payment_method_id"] = survivor_id
                duplicate["legacy"] = legacy
                redirects[duplicate_id] = survivor_id
        if redirects:
            for method in methods:
                delegate_id = str(method.get("delegates_to_payment_method_id") or "")
                if delegate_id in redirects:
                    method["delegates_to_payment_method_id"] = redirects[delegate_id]
                    method["updated_at"] = utc_now()
        return redirects

    def _paypal_credit_wrapper_candidates() -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        for method in methods:
            method_id = str(method.get("id") or "")
            name = clean_text(method.get("name") or "")
            aliases = {clean_text(alias) for alias in (method.get("aliases") or [])}
            if (
                method_id == "paypal_via_credit_card"
                or name in {"paypal via credit card", "paypal credit", "paypal via carta credito"}
                or bool(aliases & {"paypal via credit card", "paypal via credit", "paypal credit", "pay pal credit", "pay pal card"})
            ):
                candidates.append(method)
        return candidates

    def _ensure_paypal_credit_delegate() -> None:
        if "paypal" not in account_keys:
            return
        credit_delegate = _first_active_credit_method_id("main_bank") or _first_active_credit_method_id("")
        if not credit_delegate:
            credit_delegate = _ensure_default_credit_method("main_bank")

        wrappers = _paypal_credit_wrapper_candidates()
        wrapper = _method_by_id("paypal_via_credit_card") or (wrappers[0] if wrappers else None)

        if not credit_delegate:
            for candidate in wrappers:
                if _is_active_method(candidate):
                    candidate["is_active"] = False
                    candidate["is_archived"] = True
                    candidate["archived_at"] = candidate.get("archived_at") or utc_now()
                    candidate["updated_at"] = utc_now()
                    candidate.setdefault("legacy", {})["auto_archived_reason"] = "missing_active_credit_card_delegate"
            return

        if not wrapper:
            _add({
                "id": "paypal_via_credit_card",
                "name": "PayPal via Credit Card",
                "method_type": "wallet_linked_card",
                "settlement_mode": "delegated",
                "linked_account_id": "paypal",
                "delegates_to_payment_method_id": credit_delegate,
                "display_order": 75,
                "aliases": ["paypal credit", "paypal via credit", "paypal via credit card", "paypal carta credito", "paypal card credit", "pay pal credit", "pay pal card"],
                "legacy": {"migration_rule": "auto_paypal_via_credit_card"},
                "metadata": {"auto_default": True, "visible_card": True},
            })
            return

        changed = False
        if str(wrapper.get("id") or "") != "paypal_via_credit_card" and not _method_by_id("paypal_via_credit_card"):
            wrapper["id"] = "paypal_via_credit_card"
            changed = True
        if wrapper.get("is_archived") or not wrapper.get("is_active", True):
            wrapper["is_active"] = True
            wrapper["is_archived"] = False
            wrapper["archived_at"] = ""
            changed = True
        if wrapper.get("name") != "PayPal via Credit Card":
            wrapper["name"] = "PayPal via Credit Card"
            changed = True
        if wrapper.get("method_type") != "wallet_linked_card":
            wrapper["method_type"] = "wallet_linked_card"
            changed = True
        if wrapper.get("settlement_mode") != "delegated":
            wrapper["settlement_mode"] = "delegated"
            changed = True
        if wrapper.get("linked_account_id") != "paypal":
            wrapper["linked_account_id"] = "paypal"
            changed = True
        delegate = _method_by_id(str(wrapper.get("delegates_to_payment_method_id") or ""))
        delegate_bad = not _is_active_method(delegate) or not _credit_method_has_required_accounts(delegate or {}, "main_bank")
        if delegate_bad or str(wrapper.get("delegates_to_payment_method_id") or "") != credit_delegate:
            wrapper["delegates_to_payment_method_id"] = credit_delegate
            changed = True
        before_aliases = list(wrapper.get("aliases", []))
        _merge_aliases(wrapper, ["paypal credit", "paypal via credit", "paypal via credit card", "paypal carta credito", "paypal card credit", "pay pal credit", "pay pal card"])
        if before_aliases != wrapper.get("aliases", []):
            changed = True
        legacy = dict(wrapper.get("legacy") if isinstance(wrapper.get("legacy"), Mapping) else {})
        if legacy.get("auto_archived_reason") == "missing_active_credit_card_delegate":
            legacy.pop("auto_archived_reason", None)
            wrapper["legacy"] = legacy
            changed = True
        # Merge/archive additional PayPal-credit wrapper duplicates.
        for duplicate in wrappers:
            if duplicate is wrapper:
                continue
            _merge_aliases(wrapper, [*(duplicate.get("aliases") or []), duplicate.get("id") or "", duplicate.get("name") or ""])
            duplicate["is_active"] = False
            duplicate["is_archived"] = True
            duplicate["archived_at"] = duplicate.get("archived_at") or utc_now()
            duplicate["updated_at"] = utc_now()
            dup_legacy = dict(duplicate.get("legacy") if isinstance(duplicate.get("legacy"), Mapping) else {})
            dup_legacy["auto_archived_reason"] = "duplicate_paypal_credit_wrapper"
            dup_legacy["replacement_payment_method_id"] = "paypal_via_credit_card"
            duplicate["legacy"] = dup_legacy
            changed = True
        if changed:
            wrapper["updated_at"] = utc_now()

    _repair_credit_method_accounts()
    _repair_prepaid_method_accounts()

    for account in accounts:
        key = str(account.get("key") or account.get("id") or "")
        if not key or account.get("is_container") or account.get("is_liability") or not account.get("is_active", True):
            continue
        kind = clean_text(account.get("account_kind") or account.get("type") or "")
        label = account.get("label") or account.get("name") or key.replace("_", " ").title()
        order = int(_safe_number(account.get("display_order"), 1000))
        _materialize_legacy_account_cards(account)
        parent_key = str(account.get("parent_account_id") or account.get("parent_key") or "").strip()
        prepaid_card_owns_balance = kind == "prepaid_balance" and any(
            _is_active_method(method)
            and clean_text(method.get("method_type") or "") == "prepaid_card"
            and key in {
                str(method.get("linked_account_id") or ""),
                str(method.get("funding_account_id") or ""),
                str(method.get("settlement_account_id") or ""),
            }
            and str(method.get("id") or "") != key
            for method in methods
        )
        if prepaid_card_owns_balance:
            # The real prepaid card owns this balance account. Keep the account
            # directly accessible, but do not manufacture a second card-shaped
            # payment method for the same stored balance.
            for method in methods:
                legacy = method.get("legacy") if isinstance(method.get("legacy"), Mapping) else {}
                if str(method.get("id") or "") != key or legacy.get("migration_rule") != "auto_wallet_balance_method":
                    continue
                method["is_active"] = False
                method["is_archived"] = True
                method["archived_at"] = method.get("archived_at") or utc_now()
                method["updated_at"] = utc_now()
                legacy = dict(legacy)
                legacy["auto_archived_reason"] = "prepaid_balance_owned_by_card"
                method["legacy"] = legacy
            continue
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

    # Clean up provably generated card clones before building delegated wrappers.
    # This is deliberately conservative: independent user-created cards keep
    # their stable ids even when names/last-four values are identical.
    _deduplicate_generated_card_methods()
    _deduplicate_credit_methods()

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

    _ensure_paypal_credit_delegate()

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
        active = bool(method.get("is_active", True)) and not bool(method.get("is_archived", False))
        if active and method_id in active_ids:
            method["is_active"] = False
            method["is_archived"] = True
            method["archived_at"] = method.get("archived_at") or utc_now()
            method.setdefault("legacy", {})["auto_archived_reason"] = "duplicate_active_payment_method_id"
        if bool(method.get("is_active", True)) and not bool(method.get("is_archived", False)):
            active_ids.add(method_id)
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
    is_manual_card = str(form.get("manual_card") or form.get("user_created") or "").strip().casefold() in {"1", "true", "yes", "on"}
    card_payload = {
        "network": clean_label(form.get("card_network") or form.get("network") or ""),
        "last4": clean_label(form.get("card_last4") or form.get("last4") or ""),
        "holder_name": clean_label(form.get("card_holder_name") or form.get("holder_name") or ""),
        "expiry_month": clean_label(form.get("card_expiry_month") or form.get("expiry_month") or ""),
        "expiry_year": clean_label(form.get("card_expiry_year") or form.get("expiry_year") or ""),
    }
    if any(card_payload.values()):
        metadata["card"] = card_payload
    if is_manual_card or any(card_payload.values()):
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
        "parent_account_id": clean_text(form.get("parent_account_id") or ""),
        "settlement_mode": clean_text(form.get("settlement_mode") or "external_record_only"),
        "delegates_to_payment_method_id": slugify(form.get("delegates_to_payment_method_id")) if clean_text(form.get("delegates_to_payment_method_id") or "") else "",
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
        "parent_account_id": clean_text(raw.get("parent_account_id") or ""),
        "settlement_mode": settlement_mode,
        "delegates_to_payment_method_id": slugify(raw.get("delegates_to_payment_method_id")) if clean_text(raw.get("delegates_to_payment_method_id") or "") else "",
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
