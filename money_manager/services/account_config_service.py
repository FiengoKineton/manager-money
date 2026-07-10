from __future__ import annotations

import re
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from money_manager.config.user_defaults import DEFAULT_ACCOUNTS
from money_manager.services._user_config import load_user_config, save_user_config
from money_manager.config.user_paths import get_current_user_id, normalize_user_id

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

ACCOUNT_KINDS = {
    "current_account",
    "cash",
    "prepaid_balance",
    "wallet_balance",
    "dependent_wallet",
    "meal_voucher",
    "investment_cash",
    "credit_card_liability",
    "external_account",
    "container",
    "other",
}

LIQUIDITY_ROLLUP_POLICIES = {"own_only", "roll_up_to_parent", "standalone"}

_TYPE_TO_KIND = {
    "main": "current_account",
    "bank": "current_account",
    "current": "current_account",
    "current_account": "current_account",
    "cash": "cash",
    "prepaid": "prepaid_balance",
    "pre_paid": "prepaid_balance",
    "prepaid_card": "prepaid_balance",
    "pre_paid_card": "prepaid_balance",
    "prepaid_balance": "prepaid_balance",
    "wallet": "wallet_balance",
    "wallet_balance": "wallet_balance",
    "dependent_wallet": "dependent_wallet",
    "meal_voucher": "meal_voucher",
    "edenred": "meal_voucher",
    "investment": "investment_cash",
    "investment_cash": "investment_cash",
    "credit": "credit_card_liability",
    "credit_card": "credit_card_liability",
    "credit card": "credit_card_liability",
    "credit_card_liability": "credit_card_liability",
    "external": "external_account",
    "external_account": "external_account",
    "container": "container",
    "other": "other",
}

_RESERVED_FORM_KEYS = {"", "auto", "main", "bank", "credit", "card", "credit_card"}


_GENERIC_MAIN_BANK_LABELS = {"primary current account", "primary account", "main_bank", "main bank", "main bank account", "bank account", "conto corrente", "conto", "bank", "auto"}

DEFAULT_ACCOUNT_ICONS: dict[str, str] = {
    "main_bank": "🏦",
    "mediolanum": "🏦",
    "banca mediolanum": "🏦",
    "cash_flow": "💶",
    "cash": "💶",
    "paypal": "🅿️",
    "pay pal": "🅿️",
    "revolut": "🇷",
    "revoulout": "🇷",
    "edenred": "🍽️",
    "eden red": "🍽️",
    "ticket restaurant": "🍽️",
    "satispay": "🟥",
    "hype": "🟦",
    "postepay": "📮",
    "wise": "🌍",
    "n26": "🔷",
    "apple pay": "",
    "google wallet": "G",
    "google pay": "G",
    "amazon": "📦",
    "openai": "🤖",
    "chatgpt": "🤖",
    "chatgbt": "🤖",
    "credit_card": "💳",
    "other_account": "📦",
}

ACCOUNT_PRESET_OPTIONS: tuple[dict[str, str], ...] = (
    {"label": "PayPal", "type": "dependent_wallet", "icon": "🅿️", "institution": "PayPal", "parent_hint": "main_bank", "aliases": "paypal, pay pal, paypal wallet"},
    {"label": "Revolut", "type": "current_account", "icon": "🇷", "institution": "Revolut", "parent_hint": "", "aliases": "revolut, revoulout, revolut card"},
    {"label": "Edenred", "type": "meal_voucher", "icon": "🍽️", "institution": "Edenred", "parent_hint": "", "aliases": "edenred, ticket restaurant, buoni pasto, meal voucher, grocery card"},
    {"label": "Satispay", "type": "dependent_wallet", "icon": "🟥", "institution": "Satispay", "parent_hint": "main_bank", "aliases": "satispay"},
    {"label": "HYPE", "type": "current_account", "icon": "🟦", "institution": "HYPE", "parent_hint": "", "aliases": "hype, hype card"},
    {"label": "Postepay", "type": "prepaid_balance", "icon": "📮", "institution": "Poste Italiane", "parent_hint": "main_bank", "aliases": "postepay, poste pay, poste italiane"},
    {"label": "Wise", "type": "current_account", "icon": "🌍", "institution": "Wise", "parent_hint": "", "aliases": "wise, transferwise"},
    {"label": "N26", "type": "current_account", "icon": "🔷", "institution": "N26", "parent_hint": "", "aliases": "n26"},
    {"label": "Apple Pay", "type": "dependent_wallet", "icon": "", "institution": "Apple", "parent_hint": "main_bank", "aliases": "apple pay, apple wallet"},
    {"label": "Google Wallet", "type": "dependent_wallet", "icon": "G", "institution": "Google", "parent_hint": "main_bank", "aliases": "google wallet, google pay"},
    {"label": "Amazon", "type": "dependent_wallet", "icon": "📦", "institution": "Amazon", "parent_hint": "main_bank", "aliases": "amazon, amazon account"},
    {"label": "ChatGPT / OpenAI", "type": "dependent_wallet", "icon": "🤖", "institution": "OpenAI", "parent_hint": "main_bank", "aliases": "chatgpt, chatgbt, openai"},
)


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


def clean_icon(value: Any) -> str:
    text = clean_label(value)
    return text[:12]


def guess_account_icon(*values: Any, account_kind: str = "") -> str:
    parts = [clean_text(value) for value in values if clean_text(value)]
    for part in parts:
        if part in DEFAULT_ACCOUNT_ICONS:
            return DEFAULT_ACCOUNT_ICONS[part]
    blob = " ".join(parts)
    for key, icon in DEFAULT_ACCOUNT_ICONS.items():
        if key and key in blob:
            return icon
    kind = clean_text(account_kind)
    if kind == "cash":
        return "💶"
    if kind == "meal_voucher":
        return "🍽️"
    if kind in {"credit_card_liability", "prepaid_balance"}:
        return "💳"
    if kind in {"dependent_wallet", "wallet_balance"}:
        return "👛"
    if kind == "investment_cash":
        return "📈"
    if kind == "container":
        return "📦"
    return "🏦"


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
    try:
        from money_manager.cache import request_cache

        request_cache.delete_prefix("account_config_lookup:")
    except Exception:
        pass
    return save_user_config(ACCOUNTS_FILE, payload, user_id=user_id)


def _account_lookup_snapshot(user_id: str | None = None) -> dict[str, Any]:
    """Return request-local account indexes used by hot form/render paths.

    Account label/key resolution is called many times while rendering sidebars,
    payment forms, and transaction rows.  Building the alias/key maps once per
    request avoids repeated JSON decrypt/parse/normalize cycles without changing
    the persisted account structure.
    """
    safe_id = normalize_user_id(user_id or get_current_user_id()) if (user_id or get_current_user_id()) else ""
    cache_key = f"account_config_lookup:{safe_id}"
    try:
        from money_manager.cache import request_cache

        sentinel = object()
        cached = request_cache.get(cache_key, sentinel)
        if cached is not sentinel:
            return cached
    except Exception:
        request_cache = None  # type: ignore

    accounts = list(load_accounts_config(user_id=user_id).get("accounts", []) or [])
    by_key: dict[str, dict[str, Any]] = {}
    alias_map: dict[str, str] = {}
    for account in accounts:
        if not isinstance(account, Mapping):
            continue
        key = str(account.get("key") or account.get("id") or "")
        if key:
            by_key[key] = account  # keep original object identity for compatibility inside the request
        for value in [account.get("id"), account.get("key"), account.get("label"), account.get("name"), *account.get("aliases", [])]:
            alias = clean_text(value)
            if alias and key:
                alias_map[alias] = key

    payload = {"accounts": accounts, "by_key": by_key, "alias_map": alias_map}
    try:
        request_cache.set(cache_key, payload)  # type: ignore[name-defined]
    except Exception:
        pass
    return payload


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
        "schema_version": 3,
        "accounts": accounts,
        "updated_at": clean_label(incoming.get("updated_at", "")),
    }
    for key, value in incoming.items():
        if key not in payload:
            payload[key] = deepcopy(value)
    return payload




def _default_account_by_key(key: str) -> dict[str, Any]:
    for account in DEFAULT_ACCOUNTS.get("accounts", []):
        if str(account.get("key") or account.get("id") or "") == key:
            return dict(account)
    return {}


def _default_account_field(key: str, field: str, fallback: Any = "") -> Any:
    default = _default_account_by_key(key)
    value = default.get(field)
    return fallback if value in (None, "") else value


def _looks_like_key_label(key: str, label: str) -> bool:
    cleaned_label = clean_text(label)
    cleaned_key = clean_text(key.replace("_", " "))
    return cleaned_label in {clean_text(key), cleaned_key}


def _should_use_default_label(key: str, label: str) -> bool:
    if not _default_account_by_key(key):
        return False
    cleaned = clean_text(label)
    return not cleaned or cleaned in _GENERIC_MAIN_BANK_LABELS or _looks_like_key_label(key, label)


def _resolved_institution(raw: Mapping[str, Any], key: str) -> str:
    value = clean_label(raw.get("institution") or raw.get("bank") or raw.get("bank_name") or "")
    if value:
        return value
    return clean_label(_default_account_field(key, "institution", "Banca Mediolanum" if key == MAIN_ACCOUNT_KEY else ""))




def _resolved_display_order(raw: Mapping[str, Any], key: str, index: int) -> int:
    default_order = _default_account_field(key, "display_order", (index + 1) * 10)
    raw_value = raw.get("display_order")
    if raw_value in (None, ""):
        return int(parse_money(default_order, (index + 1) * 10))
    # Earlier account migrations often produced main_bank with order 10 because
    # the old default was based on row index. Repair that so Mediolanum remains
    # the first real Conto unless the user chose a clearly custom order.
    if key == MAIN_ACCOUNT_KEY and str(raw_value).strip() in {"10", "10.0"}:
        return int(parse_money(default_order, 0))
    return int(parse_money(raw_value, default_order))

def _resolved_icon(raw: Mapping[str, Any], key: str, label: str, account_kind: str) -> str:
    value = clean_icon(raw.get("icon") or "")
    if value:
        return value
    default_icon = clean_icon(_default_account_field(key, "icon", ""))
    if default_icon:
        return default_icon
    return clean_icon(guess_account_icon(key, label, raw.get("institution"), raw.get("bank"), account_kind=account_kind))

def normalize_account_record(raw: Mapping[str, Any], *, index: int = 0) -> dict[str, Any] | None:
    label = clean_label(raw.get("label") or raw.get("name") or raw.get("title"))
    key = slugify(raw.get("key") or raw.get("id") or label)
    if not key:
        return None

    if not label:
        label = key.replace("_", " ").title()
    if _should_use_default_label(key, label):
        label = _default_account_field(key, "label", label)

    account_id = slugify(raw.get("id") or key)
    if account_id in _RESERVED_FORM_KEYS:
        account_id = key

    is_container_raw = bool(raw.get("is_container", False)) or key in {OTHER_ACCOUNTS_KEY, "other_accounts", "small_accounts"}
    parent = clean_text(raw.get("parent_account_id") or raw.get("parent_key") or raw.get("parent"))
    if not parent or parent == key or is_container_raw:
        parent = ""
    if parent == "other_accounts":
        parent = OTHER_ACCOUNTS_KEY

    main_net_policy = clean_text(raw.get("main_net_policy") or "") or MAIN_NET_SEPARATE
    if key == MAIN_ACCOUNT_KEY:
        main_net_policy = MAIN_NET_AFFECTS
    if main_net_policy not in {MAIN_NET_SEPARATE, MAIN_NET_AFFECTS, MAIN_NET_CREDIT_PENDING}:
        main_net_policy = MAIN_NET_SEPARATE

    raw_type = clean_text(raw.get("type") or raw.get("account_type") or "")
    account_kind = _infer_account_kind(raw, key=key, raw_type=raw_type, main_net_policy=main_net_policy, parent=parent, is_container=is_container_raw)
    # Meal-voucher networks such as EdenRed are independent stored-balance rails,
    # not cards delegated to the main bank account.  Even if an older form saved a
    # parent, normalize them back to a standalone level-2 account.
    if account_kind == "meal_voucher":
        parent = ""
    is_credit = account_kind == "credit_card_liability" or main_net_policy == MAIN_NET_CREDIT_PENDING
    if is_credit:
        main_net_policy = MAIN_NET_CREDIT_PENDING
    if account_kind == "current_account" or key == MAIN_ACCOUNT_KEY:
        main_net_policy = MAIN_NET_AFFECTS
    is_container = account_kind == "container" or is_container_raw

    liquidity_rollup_policy = clean_text(raw.get("liquidity_rollup_policy") or "")
    if liquidity_rollup_policy not in LIQUIDITY_ROLLUP_POLICIES:
        if account_kind == "current_account" or key == MAIN_ACCOUNT_KEY:
            liquidity_rollup_policy = "own_only"
        elif account_kind == "meal_voucher":
            liquidity_rollup_policy = "standalone"
        elif parent:
            liquidity_rollup_policy = "roll_up_to_parent"
        elif key in {"cash_flow", "cashflow", "cash"} or account_kind in {"cash", "investment_cash"}:
            liquidity_rollup_policy = "standalone"
        elif bool(raw.get("is_financial_center")):
            liquidity_rollup_policy = "standalone"
        else:
            liquidity_rollup_policy = "own_only"

    explicit_financial_center = "is_financial_center" in raw or clean_text(raw.get("liquidity_rollup_policy") or "") == "standalone"
    is_current_account = bool(raw.get("is_current_account", account_kind == "current_account" or key == MAIN_ACCOUNT_KEY))
    is_dependent_account = bool(raw.get("is_dependent_account", account_kind == "dependent_wallet" or bool(parent)))

    if account_kind == "current_account" or key == MAIN_ACCOUNT_KEY:
        is_current_account = True
        is_dependent_account = False
        liquidity_rollup_policy = "own_only"
        is_financial_center = True
    elif is_credit or is_container:
        is_financial_center = False
    elif liquidity_rollup_policy == "standalone" or key in {"cash_flow", "cashflow", "cash"} or (account_kind in {"cash", "investment_cash", "meal_voucher"} and not parent) or (explicit_financial_center and bool(raw.get("is_financial_center"))):
        is_financial_center = True
        if liquidity_rollup_policy == "standalone" or not parent:
            is_dependent_account = False
    elif is_dependent_account:
        is_financial_center = False
    else:
        is_financial_center = False

    due_day = _parse_optional_day(raw.get("due_day"))
    statement_day = _parse_optional_day(raw.get("statement_day"))
    if is_credit:
        due_day = due_day or 15
    else:
        due_day = None
        statement_day = None

    aliases = split_aliases(raw.get("aliases"))
    category_aliases = split_aliases(raw.get("category_aliases") or raw.get("categories"))
    if key == MAIN_ACCOUNT_KEY:
        for main_alias in ("mediolanum", "banca mediolanum"):
            if main_alias not in aliases:
                aliases.append(main_alias)

    for value in (key, label, account_id):
        alias = clean_text(value)
        if alias and alias not in aliases:
            aliases.append(alias)
    if not category_aliases:
        category_aliases = [alias for alias in aliases]

    if key == DEFAULT_CREDIT_ACCOUNT_KEY or is_credit:
        for alias in DEFAULT_CREDIT_ALIASES:
            if alias not in aliases:
                aliases.append(alias)
            if alias not in category_aliases:
                category_aliases.append(alias)

    legacy = deepcopy(raw.get("legacy") if isinstance(raw.get("legacy"), dict) else {})
    legacy.setdefault("compatibility_fields", ["key", "type", "main_net_policy", "category_aliases", "payment_logic", "due_day", "statement_day", "cards"])
    if raw_type and raw_type != account_kind:
        legacy.setdefault("previous_type", raw_type)
    if raw.get("payment_logic"):
        legacy.setdefault("payment_logic_source", "accounts_schema_v2")

    is_active = bool(raw.get("is_active", True))
    is_closed = bool(raw.get("is_closed", False))
    archived_at = clean_label(raw.get("archived_at") or "")
    closed_at = clean_label(raw.get("closed_at") or "")
    if archived_at and "is_active" not in raw:
        is_active = False
    if closed_at:
        is_closed = True

    record: dict[str, Any] = {
        "id": account_id,
        "key": key,
        "name": label,
        "label": label,
        "account_kind": account_kind,
        "account_level": 1 if (account_kind == "current_account" or key == MAIN_ACCOUNT_KEY) else 2 if (key in {"cash_flow", "cashflow", "cash"} or (account_kind in {"cash", "investment_cash", "meal_voucher", "prepaid_balance"} and not parent and is_financial_center)) else 3 if (is_dependent_account or parent or account_kind in {"dependent_wallet", "wallet_balance"}) else 1 if is_financial_center else 0,
        # Kept for compatibility, but normalized to the professional account kind.
        "type": account_kind,
        "currency": clean_label(raw.get("currency") or "EUR") or "EUR",
        "institution": _resolved_institution(raw, key),
        "icon": _resolved_icon(raw, key, label, account_kind),
        "iban": clean_label(raw.get("iban") or ""),
        "bic_swift": clean_label(raw.get("bic_swift") or raw.get("bic") or raw.get("swift") or ""),
        "initial_balance": parse_money(raw.get("initial_balance", 0.0)),
        "description": clean_label(raw.get("description") or ""),
        "is_financial_center": bool(is_financial_center),
        "is_current_account": bool(is_current_account),
        "is_dependent_account": bool(is_dependent_account),
        "parent_account_id": parent,
        "parent_key": parent,
        "liquidity_rollup_policy": liquidity_rollup_policy,
        "is_liability": bool(raw.get("is_liability", account_kind == "credit_card_liability")),
        "is_container": is_container,
        "is_default": bool(raw.get("is_default", False)),
        "is_custom": bool(raw.get("is_custom", not raw.get("is_default", False))),
        "is_active": is_active,
        "is_closed": is_closed,
        "closed_at": closed_at,
        "replacement_account_id": clean_text(raw.get("replacement_account_id") or ""),
        "display_order": _resolved_display_order(raw, key, index),
        "aliases": aliases,
        "category_aliases": category_aliases,
        "category_match_enabled": True if is_credit else bool(raw.get("category_match_enabled", True)),
        "category_match_mode": clean_text(raw.get("category_match_mode") or (MAIN_NET_CREDIT_PENDING if is_credit else CATEGORY_MATCH_TOP_UP_SHADOW)) or CATEGORY_MATCH_TOP_UP_SHADOW,
        "main_net_policy": main_net_policy,
        "metadata": deepcopy(raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}),
        "legacy": legacy,
        "created_at": clean_label(raw.get("created_at") or ""),
        "updated_at": clean_label(raw.get("updated_at") or ""),
        "archived_at": archived_at,
        # Legacy compatibility fields retained until the ledger prompts replace them.
        "payment_logic": _normalize_payment_logic(raw.get("payment_logic"), {
            "key": key,
            "type": account_kind,
            "account_kind": account_kind,
            "main_net_policy": main_net_policy,
            "is_container": is_container,
        }),
        "due_day": due_day,
        "statement_day": statement_day,
        "cards": normalize_cards(raw.get("cards")),
    }
    for raw_key, raw_value in raw.items():
        if raw_key not in record:
            record[raw_key] = deepcopy(raw_value)
    return record


def _infer_account_kind(
    raw: Mapping[str, Any],
    *,
    key: str,
    raw_type: str,
    main_net_policy: str,
    parent: str,
    is_container: bool,
) -> str:
    if key == MAIN_ACCOUNT_KEY:
        return "current_account"
    if key == DEFAULT_CREDIT_ACCOUNT_KEY or main_net_policy == MAIN_NET_CREDIT_PENDING:
        return "credit_card_liability"
    explicit = clean_text(raw.get("account_kind") or "")
    if explicit in ACCOUNT_KINDS:
        return explicit
    if is_container or key in {OTHER_ACCOUNTS_KEY, "other_accounts", "small_accounts"}:
        return "container"
    if key == "cash_flow":
        return "cash"
    if key == "pre_paid_card":
        return "prepaid_balance"
    if key == "edenred":
        return "meal_voucher"
    if key == "paypal":
        return "dependent_wallet" if parent else "wallet_balance"
    mapped = _TYPE_TO_KIND.get(raw_type)
    if mapped:
        return "dependent_wallet" if mapped == "wallet_balance" and parent else mapped
    if parent:
        return "dependent_wallet"
    return "other"

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
    account_kind = clean_text(account.get("account_kind") or account_type)
    is_container = bool(account.get("is_container")) or account_kind == "container"

    if policy == MAIN_NET_AFFECTS or account_type == "main" or account_kind == "current_account":
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

    if policy == MAIN_NET_CREDIT_PENDING or account_type == "credit_card" or account_kind == "credit_card_liability":
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
    accounts = _account_lookup_snapshot(user_id=user_id).get("accounts", [])
    result: list[dict[str, Any]] = []
    for account in accounts:
        if not include_main and account.get("key") == MAIN_ACCOUNT_KEY:
            continue
        if not include_archived and (not account.get("is_active", True) or account.get("is_archived") or account.get("is_closed")):
            continue
        result.append(account)
    return result


def active_accounts(user_id: str | None = None, *, include_main: bool = True) -> list[dict[str, Any]]:
    return all_accounts(user_id=user_id, include_archived=False, include_main=include_main)


def account_by_key(key: str | None, user_id: str | None = None, *, include_archived: bool = True) -> dict[str, Any] | None:
    wanted = normalize_account_key(key, user_id=user_id)
    account = _account_lookup_snapshot(user_id=user_id).get("by_key", {}).get(wanted)
    if not account:
        return None
    if not include_archived and (not account.get("is_active", True) or account.get("is_archived") or account.get("is_closed")):
        return None
    return account


def account_alias_map(user_id: str | None = None) -> dict[str, str]:
    return dict(_account_lookup_snapshot(user_id=user_id).get("alias_map", {}))


def configured_account_key(value: str | None, user_id: str | None = None) -> str | None:
    """Resolve a configured account without silently falling back to Main.

    Legacy imports intentionally use :func:`normalize_account_key`, where an
    unknown value is treated as the historical main-bank route. Interactive
    forms and stable ids must be stricter: a misspelled/removed account must not
    unexpectedly become Main.
    """
    text = clean_text(value)
    if text in {"", "auto", "main", "bank", "main bank", "main bank account", "bank account", "conto", "conto corrente"}:
        return MAIN_ACCOUNT_KEY
    if text == "other_accounts":
        text = OTHER_ACCOUNTS_KEY
    snapshot = _account_lookup_snapshot(user_id=user_id)
    if text in snapshot.get("by_key", {}):
        return text
    resolved = snapshot.get("alias_map", {}).get(text)
    return str(resolved) if resolved else None


def normalize_account_key(value: str | None, user_id: str | None = None) -> str:
    return configured_account_key(value, user_id=user_id) or MAIN_ACCOUNT_KEY


def account_label_for_key(key: str | None, user_id: str | None = None) -> str:
    wanted = normalize_account_key(key, user_id=user_id)
    account = _account_lookup_snapshot(user_id=user_id).get("by_key", {}).get(wanted)
    if account:
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
        if policy == MAIN_NET_CREDIT_PENDING or account.get("type") == "credit_card" or account.get("account_kind") == "credit_card_liability":
            kind = "credit"
        elif account.get("is_container") or account.get("account_kind") == "container":
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
    form_type = clean_text(form.get("type") or form.get("account_kind") or "wallet_balance") or "wallet_balance"
    form_policy = clean_text(form.get("main_net_policy") or "") or MAIN_NET_SEPARATE
    if form_type in {"credit_card", "credit_card_liability"}:
        form_policy = MAIN_NET_CREDIT_PENDING
    record = normalize_account_record({
        "id": key,
        "key": key,
        "label": label,
        "name": label,
        "account_kind": _TYPE_TO_KIND.get(form_type, form_type if form_type in ACCOUNT_KINDS else "other"),
        "type": _TYPE_TO_KIND.get(form_type, form_type if form_type in ACCOUNT_KINDS else "other"),
        "currency": form.get("currency") or "EUR",
        "institution": form.get("institution") or "",
        "iban": form.get("iban") or "",
        "bic_swift": form.get("bic_swift") or "",
        "initial_balance": form.get("initial_balance") or 0,
        "description": form.get("description") or "",
        "icon": form.get("icon") or guess_account_icon(key, label, form.get("institution"), account_kind=form_type),
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
        requested_type = clean_text(form.get("type") or form.get("account_kind") or account.get("account_kind") or account.get("type") or "wallet_balance") or "wallet_balance"
        if key == MAIN_ACCOUNT_KEY:
            # Main route can be labelled/annotated, but not made separate or archived.
            forced_policy = MAIN_NET_AFFECTS
        elif requested_type in {"credit_card", "credit_card_liability"}:
            forced_policy = MAIN_NET_CREDIT_PENDING
        else:
            forced_policy = form.get("main_net_policy") or account.get("main_net_policy") or MAIN_NET_SEPARATE
        parent = clean_text(form.get("parent_account_id") if "parent_account_id" in form else account.get("parent_account_id") or account.get("parent_key"))
        if parent in {"none", "top", "top_level", key} or account.get("is_container"):
            parent = ""
        updated = dict(account)
        if "type" in form or "account_kind" in form:
            mapped_kind = _TYPE_TO_KIND.get(requested_type, requested_type if requested_type in ACCOUNT_KINDS else account.get("account_kind", "other"))
            updated["account_kind"] = mapped_kind
            updated["type"] = mapped_kind
        for field in ["label", "name", "currency", "institution", "iban", "bic_swift", "description", "category_match_mode", "icon"]:
            if field in form:
                updated[field] = clean_icon(form.get(field)) if field == "icon" else clean_label(form.get(field))
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
            account["is_closed"] = False if active else bool(account.get("is_closed", False))
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


def set_default_account(account_key: str, user_id: str | None = None) -> bool:
    """Mark one current account as the user's default current account.

    This only updates accounts.json flags. profile.json is updated by callers that
    own profile defaults. Non-current/container/liability accounts are rejected.
    """
    config = load_accounts_config(user_id=user_id)
    key = normalize_account_key(account_key, user_id=user_id)
    matched = False
    for account in config.get("accounts", []):
        account_key_value = str(account.get("key") or account.get("id") or "")
        is_current = bool(account.get("is_current_account")) or str(account.get("account_kind") or account.get("type") or "") == "current_account"
        if account_key_value == key:
            if not is_current or account.get("is_container") or account.get("is_closed") or not account.get("is_active", True):
                return False
            matched = True
            account["is_default"] = True
            account["updated_at"] = utc_now()
        elif is_current:
            account["is_default"] = False
    if matched:
        save_accounts_config(config, user_id=user_id)
        _notify_cache_changed()
    return matched
