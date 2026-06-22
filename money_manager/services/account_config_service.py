from __future__ import annotations

import re
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from money_manager.config.user_defaults import DEFAULT_ACCOUNTS
from money_manager.services._user_config import load_user_config, save_user_config

ACCOUNTS_FILE = "accounts.json"

MAIN_NET_SEPARATE = "separate_when_explicit"
MAIN_NET_AFFECTS = "affects_main_net"
MAIN_NET_CREDIT_PENDING = "credit_pending"
CATEGORY_MATCH_TOP_UP_SHADOW = "top_up_shadow"
MAIN_ACCOUNT_KEY = "main_bank"
OTHER_ACCOUNTS_KEY = "other_account"
DEFAULT_CREDIT_ACCOUNT_KEY = "credit_card"
DEFAULT_CREDIT_ALIASES = [
    "credit",
    "credit card",
    "credit cards",
    "card credit",
    "carta credito",
    "carta di credito",
]

_RESERVED_FORM_KEYS = {"", "auto", "main", "bank", "credit", "card", "credit_card"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slugify(value: Any) -> str:
    text = clean_text(value)
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "custom_account"


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


def parse_money(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        return round(float(str(value).replace(",", ".")), 2)
    except (TypeError, ValueError):
        return default


def load_accounts_config(user_id: str | None = None) -> dict[str, Any]:
    """Load and repair the current user's account configuration.

    The file may contain old v1 records, a raw list, or the current schema.  The
    normalizer keeps unknown metadata fields, but guarantees every account has
    stable routing fields, including ``payment_logic``. When an old file is
    missing these fields, it is repaired so every payment flow can read the same
    account rules from accounts.json.
    """
    raw = load_user_config(ACCOUNTS_FILE, user_id=user_id)
    normalized = normalize_accounts_config(raw)
    if normalized != raw:
        try:
            save_user_config(ACCOUNTS_FILE, normalized, user_id=user_id)
        except RuntimeError:
            # Import-time/default calls may happen before a user session exists.
            # In that case return the repaired in-memory config and persist it on
            # the first request or explicit user-scoped call.
            pass
    return normalized


def save_accounts_config(config: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    payload = normalize_accounts_config(config)
    payload["updated_at"] = utc_now()
    return save_user_config(ACCOUNTS_FILE, payload, user_id=user_id)


def ensure_accounts_config(user_id: str | None = None) -> dict[str, Any]:
    return load_accounts_config(user_id=user_id)


def normalize_accounts_config(config: Mapping[str, Any] | list[Mapping[str, Any]] | None) -> dict[str, Any]:
    incoming: Mapping[str, Any]
    if isinstance(config, list):
        incoming = {"accounts": config}
    elif isinstance(config, Mapping):
        incoming = config
    else:
        incoming = {}

    records = incoming.get("accounts", [])
    if not isinstance(records, list) or not records:
        records = deepcopy(DEFAULT_ACCOUNTS["accounts"])

    accounts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(records):
        if not isinstance(raw, Mapping):
            continue
        normalized = normalize_account_record(raw, index=index)
        if not normalized:
            continue
        key = normalized["key"]
        if key in seen:
            continue
        accounts.append(normalized)
        seen.add(key)

    # Guarantee a usable main route and a generic container for all users.  These
    # are generic app-level defaults, not personal user-specific data.
    for default in DEFAULT_ACCOUNTS["accounts"]:
        default_key = str(default.get("key") or default.get("id") or "")
        if default_key and default_key not in seen:
            accounts.append(normalize_account_record(default, index=len(accounts)))
            seen.add(default_key)

    accounts.sort(key=lambda item: (int(item.get("display_order", 1000) if item.get("display_order", None) not in (None, "") else 1000), item.get("label", "")))

    payload = {
        "schema_version": 2,
        "accounts": accounts,
        "updated_at": clean_label(incoming.get("updated_at", "")),
    }
    for key, value in incoming.items():
        if key not in payload:
            payload[key] = deepcopy(value)
    return payload


def normalize_account_record(raw: Mapping[str, Any], *, index: int = 0) -> dict[str, Any] | None:
    label = clean_label(raw.get("label") or raw.get("name") or raw.get("title"))
    key = slugify(raw.get("key") or raw.get("id") or label)
    if not key:
        return None

    # Preserve old records where name existed but label did not.
    if not label:
        label = key.replace("_", " ").title()

    # Stable field aliases.
    account_id = slugify(raw.get("id") or key)
    if account_id in _RESERVED_FORM_KEYS:
        account_id = key

    is_container = bool(raw.get("is_container", False)) or key in {OTHER_ACCOUNTS_KEY, "other_accounts", "small_accounts"}
    parent = clean_text(raw.get("parent_account_id") or raw.get("parent_key") or raw.get("parent"))
    if not parent or parent == key or is_container:
        parent = ""
    if parent == "other_accounts":
        parent = OTHER_ACCOUNTS_KEY

    aliases = split_aliases(raw.get("aliases"))
    category_aliases = split_aliases(raw.get("category_aliases") or raw.get("categories"))
    for value in (key, label):
        alias = clean_text(value)
        if alias and alias not in aliases:
            aliases.append(alias)
    if not category_aliases:
        category_aliases = [alias for alias in aliases]

    if key == DEFAULT_CREDIT_ACCOUNT_KEY:
        for alias in DEFAULT_CREDIT_ALIASES:
            if alias not in aliases:
                aliases.append(alias)
            if alias not in category_aliases:
                category_aliases.append(alias)

    main_net_policy = clean_text(raw.get("main_net_policy") or "") or MAIN_NET_SEPARATE
    if key == MAIN_ACCOUNT_KEY:
        main_net_policy = MAIN_NET_AFFECTS
    if main_net_policy not in {MAIN_NET_SEPARATE, MAIN_NET_AFFECTS, MAIN_NET_CREDIT_PENDING}:
        main_net_policy = MAIN_NET_SEPARATE

    account_type = clean_text(raw.get("type") or raw.get("account_type") or "wallet") or "wallet"
    if key == DEFAULT_CREDIT_ACCOUNT_KEY:
        account_type = "credit_card"
        main_net_policy = MAIN_NET_CREDIT_PENDING
    if account_type == "credit card":
        account_type = "credit_card"
    if main_net_policy == MAIN_NET_CREDIT_PENDING:
        account_type = "credit_card"
    if account_type == "credit_card" and main_net_policy == MAIN_NET_SEPARATE:
        # A credit-card account should use credit/pending routing unless the
        # user explicitly chooses a main-net wallet policy later.
        main_net_policy = MAIN_NET_CREDIT_PENDING

    due_day = _parse_optional_day(raw.get("due_day"))
    statement_day = _parse_optional_day(raw.get("statement_day"))
    if account_type == "credit_card" or main_net_policy == MAIN_NET_CREDIT_PENDING:
        due_day = due_day or 15
    else:
        due_day = None
        statement_day = None

    cards = normalize_cards(raw.get("cards"))

    record: dict[str, Any] = {
        "id": account_id,
        "key": key,
        "name": label,
        "label": label,
        "type": account_type,
        "currency": clean_label(raw.get("currency") or "EUR") or "EUR",
        "institution": clean_label(raw.get("institution") or raw.get("bank") or ""),
        "iban": clean_label(raw.get("iban") or ""),
        "initial_balance": parse_money(raw.get("initial_balance", 0.0)),
        "description": clean_label(raw.get("description") or ""),
        "aliases": aliases,
        "category_aliases": category_aliases,
        "category_match_enabled": True if key == DEFAULT_CREDIT_ACCOUNT_KEY else bool(raw.get("category_match_enabled", True)),
        "category_match_mode": clean_text(raw.get("category_match_mode") or CATEGORY_MATCH_TOP_UP_SHADOW) or CATEGORY_MATCH_TOP_UP_SHADOW,
        "main_net_policy": main_net_policy,
        "parent_account_id": parent or None,
        "parent_key": parent,
        "is_container": is_container,
        "is_default": bool(raw.get("is_default", False)),
        "is_custom": bool(raw.get("is_custom", not raw.get("is_default", False))),
        "is_active": bool(raw.get("is_active", True)),
        "display_order": int(parse_money(raw.get("display_order", (index + 1) * 10), (index + 1) * 10)),
        "due_day": due_day,
        "statement_day": statement_day,
        "payment_logic": _normalize_payment_logic(raw.get("payment_logic"), {
            "key": key,
            "type": account_type,
            "main_net_policy": main_net_policy,
            "is_container": is_container,
        }),
        "cards": cards,
        "metadata": deepcopy(raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}),
        "archived_at": clean_label(raw.get("archived_at") or ""),
        "created_at": clean_label(raw.get("created_at") or ""),
        "updated_at": clean_label(raw.get("updated_at") or ""),
    }
    # Preserve unknown fields for forward/backward compatibility.
    for raw_key, raw_value in raw.items():
        if raw_key not in record:
            record[raw_key] = deepcopy(raw_value)
    return record


def normalize_cards(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    cards: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, Mapping):
            continue
        label = clean_label(item.get("label") or item.get("name") or item.get("last4"))
        if not label:
            continue
        card_id = clean_label(item.get("id")) or uuid.uuid4().hex
        if card_id in seen:
            card_id = uuid.uuid4().hex
        seen.add(card_id)
        cards.append({
            "id": card_id,
            "label": label,
            "card_type": clean_text(item.get("card_type") or item.get("type") or "debit") or "debit",
            "last4": clean_label(item.get("last4") or ""),
            "network": clean_label(item.get("network") or ""),
            "is_active": bool(item.get("is_active", True)),
            "created_at": clean_label(item.get("created_at") or ""),
            "archived_at": clean_label(item.get("archived_at") or ""),
        })
    return cards


def _parse_day(value: Any) -> int:
    day = _parse_optional_day(value)
    return day or 15


def _parse_optional_day(value: Any) -> int | None:
    try:
        day = int(str(value or "").strip())
    except (TypeError, ValueError):
        return None
    if 1 <= day <= 31:
        return day
    return None


def _default_payment_logic_for_normalized_account(account: Mapping[str, Any]) -> dict[str, Any]:
    policy = clean_text(account.get("main_net_policy") or MAIN_NET_SEPARATE)
    account_type = clean_text(account.get("type") or "wallet")
    is_container = bool(account.get("is_container"))

    if policy == MAIN_NET_AFFECTS or account_type == "main":
        return {
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
        }

    if policy == MAIN_NET_CREDIT_PENDING or account_type == "credit_card":
        return {
            "schema_version": 1,
            "mode": "credit_statement",
            "default_method": "credit",
            "allowed_methods": ["credit"],
            "default_insufficient_action": "stop",
            "insufficient_actions": [],
            "show_method_selector": False,
            "can_pay_from": True,
            "affects_main_net_now": False,
            "creates_pending": True,
        }

    if is_container:
        return {
            "schema_version": 1,
            "mode": "container",
            "default_method": "balance",
            "allowed_methods": ["balance"],
            "default_insufficient_action": "stop",
            "insufficient_actions": ["stop"],
            "show_method_selector": False,
            "can_pay_from": False,
            "affects_main_net_now": False,
            "creates_pending": False,
        }

    return {
        "schema_version": 1,
        "mode": "tracked_balance",
        "default_method": "balance",
        "allowed_methods": ["balance", "credit", "another_card"],
        "default_insufficient_action": "stop",
        "insufficient_actions": ["stop", "use_another_card_for_remaining", "use_credit_for_remaining"],
        "show_method_selector": True,
        "can_pay_from": True,
        "affects_main_net_now": False,
        "creates_pending": False,
    }


def _normalize_payment_logic(raw: Any, account: Mapping[str, Any]) -> dict[str, Any]:
    logic = _default_payment_logic_for_normalized_account(account)
    if not isinstance(raw, Mapping):
        return logic

    mode = clean_text(raw.get("mode") or logic.get("mode"))
    if mode in {"main_net", "tracked_balance", "credit_statement", "container"}:
        logic["mode"] = mode

    allowed_methods = _clean_string_list(raw.get("allowed_methods"))
    if allowed_methods:
        logic["allowed_methods"] = allowed_methods

    default_method = clean_text(raw.get("default_method") or logic.get("default_method"))
    if default_method in set(logic.get("allowed_methods") or []):
        logic["default_method"] = default_method

    insufficient_actions = _clean_string_list(raw.get("insufficient_actions"))
    if insufficient_actions:
        logic["insufficient_actions"] = insufficient_actions

    default_action = clean_text(raw.get("default_insufficient_action") or logic.get("default_insufficient_action"))
    if default_action in set(logic.get("insufficient_actions") or []) or not logic.get("insufficient_actions"):
        logic["default_insufficient_action"] = default_action or "stop"

    for flag in ["show_method_selector", "can_pay_from", "affects_main_net_now", "creates_pending"]:
        if flag in raw:
            logic[flag] = bool(raw.get(flag))
    return logic


def _clean_string_list(value: Any) -> list[str]:
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


def all_accounts(user_id: str | None = None, *, include_archived: bool = True, include_main: bool = True) -> list[dict[str, Any]]:
    accounts = load_accounts_config(user_id=user_id).get("accounts", [])
    result: list[dict[str, Any]] = []
    for account in accounts:
        if not include_main and account.get("key") == MAIN_ACCOUNT_KEY:
            continue
        if not include_archived and not account.get("is_active", True):
            continue
        result.append(account)
    return result


def active_accounts(user_id: str | None = None, *, include_main: bool = True) -> list[dict[str, Any]]:
    return all_accounts(user_id=user_id, include_archived=False, include_main=include_main)


def account_by_key(key: str | None, user_id: str | None = None, *, include_archived: bool = True) -> dict[str, Any] | None:
    wanted = normalize_account_key(key, user_id=user_id)
    for account in all_accounts(user_id=user_id, include_archived=include_archived, include_main=True):
        if account.get("key") == wanted:
            return account
    return None


def account_alias_map(user_id: str | None = None) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for account in all_accounts(user_id=user_id, include_archived=True, include_main=True):
        key = str(account.get("key") or "")
        for value in [account.get("id"), account.get("key"), account.get("label"), account.get("name"), *account.get("aliases", [])]:
            alias = clean_text(value)
            if alias:
                mapping[alias] = key
    return mapping


def normalize_account_key(value: str | None, user_id: str | None = None) -> str:
    text = clean_text(value)
    if text in {"", "auto", "main", "bank", "main bank", "main bank account", "bank account", "conto", "conto corrente"}:
        return MAIN_ACCOUNT_KEY
    if text == "other_accounts":
        text = OTHER_ACCOUNTS_KEY
    return account_alias_map(user_id=user_id).get(text, MAIN_ACCOUNT_KEY)


def account_label_for_key(key: str | None, user_id: str | None = None) -> str:
    wanted = normalize_account_key(key, user_id=user_id)
    for account in all_accounts(user_id=user_id, include_archived=True, include_main=True):
        if account.get("key") == wanted:
            return str(account.get("label") or account.get("name") or wanted)
    return "Main bank account"


def account_description_for_key(key: str | None, user_id: str | None = None) -> str:
    account = account_by_key(key, user_id=user_id, include_archived=True)
    if not account:
        return ""
    return str(account.get("description") or "")


def account_policy_for_key(key: str | None, user_id: str | None = None) -> str:
    account = account_by_key(key, user_id=user_id, include_archived=True)
    if not account:
        return MAIN_NET_AFFECTS
    return str(account.get("main_net_policy") or MAIN_NET_SEPARATE)


def account_due_day_for_key(key: str | None, user_id: str | None = None, default: int = 15) -> int:
    account = account_by_key(key, user_id=user_id, include_archived=True)
    if not account:
        return default
    return _parse_day(account.get("due_day") or default)


def account_parent_key(key: str | None, user_id: str | None = None) -> str:
    account = account_by_key(key, user_id=user_id, include_archived=True)
    if not account:
        return ""
    return str(account.get("parent_account_id") or account.get("parent_key") or "")


def category_aliases_by_key(user_id: str | None = None) -> dict[str, set[str]]:
    mapping: dict[str, set[str]] = {}
    for account in all_accounts(user_id=user_id, include_archived=True, include_main=False):
        if not account.get("category_match_enabled", True):
            continue
        aliases = set(split_aliases(account.get("category_aliases")))
        aliases.update(split_aliases(account.get("aliases")))
        for value in [account.get("id"), account.get("key"), account.get("label"), account.get("name")]:
            alias = clean_text(value)
            if alias:
                aliases.add(alias)
        mapping[str(account.get("key"))] = aliases
    return mapping


def non_main_account_keys(user_id: str | None = None, *, include_archived: bool = True) -> set[str]:
    return {str(account.get("key")) for account in all_accounts(user_id=user_id, include_archived=include_archived, include_main=False)}


def account_display_options(user_id: str | None = None, *, include_archived: bool = False, include_containers: bool = True) -> list[dict[str, Any]]:
    accounts = all_accounts(user_id=user_id, include_archived=include_archived, include_main=False)
    options: list[dict[str, Any]] = []
    for account in accounts:
        if account.get("is_container") and not include_containers:
            continue
        label = str(account.get("label") or account.get("name") or account.get("key"))
        parent = str(account.get("parent_account_id") or account.get("parent_key") or "")
        display = label
        if parent:
            parent_label = account_label_for_key(parent, user_id=user_id)
            display = f"{parent_label} / {label}"
        option = deepcopy(account)
        policy = str(account.get("main_net_policy") or MAIN_NET_SEPARATE)
        if policy == MAIN_NET_CREDIT_PENDING or account.get("type") == "credit_card":
            kind = "credit"
        elif account.get("is_container"):
            kind = "container"
        else:
            kind = "auxiliary"
        option.update({
            "label": display,
            "display_label": label,
            # New forms store the stable account key. Old CSV rows with labels
            # still resolve through aliases/snapshots.
            "value": str(account.get("key") or label),
            "kind": kind,
            "parent_key": parent,
        })
        options.append(option)
    return options


def create_account_from_form(form: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any] | None:
    label = clean_label(form.get("label") or form.get("name"))
    if not label:
        return None
    config = load_accounts_config(user_id=user_id)
    accounts = config["accounts"]
    key = slugify(form.get("key") or label)
    if key == MAIN_ACCOUNT_KEY:
        return None
    existing_keys = {str(account.get("key")) for account in accounts}
    if key in existing_keys:
        # Make account creation idempotent: edit the existing row instead of duplicating.
        return update_account_from_form(key, form, user_id=user_id)
    parent = clean_text(form.get("parent_account_id") or form.get("parent_key") or "")
    if parent in {"none", "top", "top_level"}:
        parent = ""
    form_type = clean_text(form.get("type") or "wallet") or "wallet"
    form_policy = clean_text(form.get("main_net_policy") or "") or MAIN_NET_SEPARATE
    if form_type == "credit_card":
        form_policy = MAIN_NET_CREDIT_PENDING
    record = normalize_account_record({
        "id": key,
        "key": key,
        "label": label,
        "name": label,
        "type": form_type,
        "currency": form.get("currency") or "EUR",
        "institution": form.get("institution") or "",
        "iban": form.get("iban") or "",
        "initial_balance": form.get("initial_balance") or 0,
        "description": form.get("description") or "",
        "aliases": split_aliases(form.get("aliases")) or [label],
        "category_aliases": split_aliases(form.get("category_aliases")) or split_aliases(form.get("aliases")) or [label],
        "category_match_enabled": str(form.get("category_match_enabled", "1")).lower() not in {"0", "false", "off", "no"},
        "category_match_mode": form.get("category_match_mode") or CATEGORY_MATCH_TOP_UP_SHADOW,
        "main_net_policy": form_policy,
        "parent_account_id": parent or None,
        "is_container": str(form.get("is_container", "")).lower() in {"1", "true", "on", "yes"},
        "is_default": False,
        "is_custom": True,
        "is_active": True,
        "display_order": form.get("display_order") or (len(accounts) + 1) * 10,
        "due_day": form.get("due_day") or 15,
        "statement_day": form.get("statement_day") or "",
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }, index=len(accounts))
    if record is None:
        return None
    accounts.append(record)
    save_accounts_config(config, user_id=user_id)
    _notify_cache_changed()
    return record


def update_account_from_form(account_key: str, form: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any] | None:
    config = load_accounts_config(user_id=user_id)
    key = normalize_account_key(account_key, user_id=user_id)
    for index, account in enumerate(config["accounts"]):
        if account.get("key") != key:
            continue
        requested_type = clean_text(form.get("type") or account.get("type") or "wallet") or "wallet"
        if key == MAIN_ACCOUNT_KEY:
            # Main route can be labelled/annotated, but not made separate or archived.
            forced_policy = MAIN_NET_AFFECTS
        elif requested_type == "credit_card":
            forced_policy = MAIN_NET_CREDIT_PENDING
        else:
            forced_policy = form.get("main_net_policy") or account.get("main_net_policy") or MAIN_NET_SEPARATE
        parent = clean_text(form.get("parent_account_id") if "parent_account_id" in form else account.get("parent_account_id") or account.get("parent_key"))
        if parent in {"none", "top", "top_level", key} or account.get("is_container"):
            parent = ""
        updated = dict(account)
        for field in ["label", "name", "type", "currency", "institution", "iban", "description", "category_match_mode"]:
            if field in form:
                updated[field] = clean_label(form.get(field))
        if "label" in form and form.get("label"):
            updated["name"] = clean_label(form.get("label"))
        if "initial_balance" in form:
            updated["initial_balance"] = parse_money(form.get("initial_balance"), parse_money(account.get("initial_balance")))
        if "aliases" in form:
            updated["aliases"] = split_aliases(form.get("aliases"))
        if "category_aliases" in form:
            updated["category_aliases"] = split_aliases(form.get("category_aliases"))
        if "category_match_enabled" in form:
            updated["category_match_enabled"] = str(form.get("category_match_enabled", "")).lower() in {"1", "true", "on", "yes"}
        elif key != MAIN_ACCOUNT_KEY:
            updated["category_match_enabled"] = False if form.get("_category_match_checkbox_present") == "1" else account.get("category_match_enabled", True)
        updated["main_net_policy"] = forced_policy
        updated["parent_account_id"] = parent or None
        updated["parent_key"] = parent
        if "is_container" in form:
            updated["is_container"] = str(form.get("is_container", "")).lower() in {"1", "true", "on", "yes"}
        if "display_order" in form:
            updated["display_order"] = int(parse_money(form.get("display_order"), account.get("display_order", index * 10)))
        if "due_day" in form:
            updated["due_day"] = _parse_day(form.get("due_day"))
        if "statement_day" in form:
            updated["statement_day"] = _parse_optional_day(form.get("statement_day"))
        updated["updated_at"] = utc_now()
        config["accounts"][index] = normalize_account_record(updated, index=index) or updated
        save_accounts_config(config, user_id=user_id)
        _notify_cache_changed()
        return config["accounts"][index]
    return None


def archive_account(account_key: str, user_id: str | None = None, active: bool = False) -> bool:
    config = load_accounts_config(user_id=user_id)
    key = normalize_account_key(account_key, user_id=user_id)
    if key == MAIN_ACCOUNT_KEY:
        return False
    changed = False
    for account in config["accounts"]:
        if account.get("key") == key:
            account["is_active"] = active
            account["archived_at"] = "" if active else utc_now()
            account["updated_at"] = utc_now()
            changed = True
            break
    if changed:
        save_accounts_config(config, user_id=user_id)
        _notify_cache_changed()
    return changed


def restore_account(account_key: str, user_id: str | None = None) -> bool:
    return archive_account(account_key, user_id=user_id, active=True)


def add_card_to_account(account_key: str, form: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any] | None:
    config = load_accounts_config(user_id=user_id)
    key = normalize_account_key(account_key, user_id=user_id)
    label = clean_label(form.get("card_label") or form.get("label"))
    if not label:
        return None
    card = {
        "id": uuid.uuid4().hex,
        "label": label,
        "card_type": clean_text(form.get("card_type") or "debit") or "debit",
        "last4": clean_label(form.get("last4") or ""),
        "network": clean_label(form.get("network") or ""),
        "is_active": True,
        "created_at": utc_now(),
        "archived_at": "",
    }
    for account in config["accounts"]:
        if account.get("key") == key:
            account.setdefault("cards", [])
            account["cards"].append(card)
            account["updated_at"] = utc_now()
            save_accounts_config(config, user_id=user_id)
            return card
    return None


def archive_card(account_key: str, card_id: str, user_id: str | None = None, active: bool = False) -> bool:
    config = load_accounts_config(user_id=user_id)
    key = normalize_account_key(account_key, user_id=user_id)
    changed = False
    for account in config["accounts"]:
        if account.get("key") != key:
            continue
        for card in account.get("cards", []):
            if str(card.get("id")) == str(card_id):
                card["is_active"] = active
                card["archived_at"] = "" if active else utc_now()
                changed = True
                break
    if changed:
        save_accounts_config(config, user_id=user_id)
    return changed


def _notify_cache_changed() -> None:
    try:
        from money_manager.services.cache_service import notify_data_changed
        notify_data_changed()
    except Exception:
        pass
