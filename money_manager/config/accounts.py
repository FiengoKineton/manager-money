"""Account configuration and runtime-custom liquid accounts.

The app still keeps expenses.csv, incomes.csv and investments.csv as the main
source of truth. The ``account`` column is a routing tag:
- blank / Main bank / credit-card settlement rows affect the main account;
- PayPal is a separate liquid account unless the explicit PayPal-credit route is used;
- liquid account rows are analysed separately; top-ups can still affect the tracked main net;
- custom liquid accounts are stored in ``data/accounts.json``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
CUSTOM_ACCOUNTS_JSON = DATA_DIR / "accounts.json"

MAIN_ACCOUNT_KEY = "main_bank"
MAIN_ACCOUNT_LABEL = "Main bank account"
CREDIT_OPTION_KEY = "credit_card"
PAYPAL_ACCOUNT_KEY = "paypal"
PAYPAL_CREDIT_ACCOUNT_VALUE = "paypal_credit"
PAYPAL_CREDIT_ALIASES = {"paypal_credit", "paypal credit", "pay pal credit", "paypal card", "pay pal card"}
PAYPAL_OPTION_KEY = PAYPAL_ACCOUNT_KEY

# These are the built-in non-main accounts.  The third one intentionally acts as
# a generic "other account" bucket and also catches old Ticket Restaurant rows.
DEFAULT_AUXILIARY_ACCOUNTS = [
    {
        "key": "cash_flow",
        "label": "Cash Flow",
        "description": "Physical cash you still have available.",
        "aliases": ["cash", "cash flow", "contanti", "physical cash"],
        "category_aliases": ["cash", "cash flow", "contanti", "physical cash"],
        "is_custom": False,
    },
    {
        "key": "pre_paid_card",
        "label": "Pre-paid card",
        "description": "Money available on a pre-paid card.",
        "aliases": [
            "pre-paid card",
            "prepaid card",
            "pre paid card",
            "pre-paid",
            "prepaid",
            "postepay",
            "carta prepagata",
        ],
        "category_aliases": [
            "pre-paid card",
            "prepaid card",
            "pre paid card",
            "pre-paid",
            "prepaid",
            "postepay",
            "carta prepagata",
        ],
        "is_custom": False,
    },
    {
        "key": "edenred",
        "label": "EdenRed",
        "description": "Meal-voucher / EdenRed balance tracked as a separate liquid account.",
        "aliases": ["edenred", "eden red", "edenred card", "eden red card"],
        "category_aliases": ["edenred", "eden red", "edenred card", "eden red card"],
        "is_custom": False,
    },
    {
        "key": "other_account",
        "label": "Other account",
        "description": "Parent bucket for smaller external credit/balance accounts such as Glovo or EasyPark.",
        "aliases": [
            "other account",
            "other card",
            "ticketrestaurant",
            "ticket restaurant",
            "ticket restaurants",
            "ticket",
            "buoni pasto",
            "meal vouchers",
            "meal voucher",
        ],
        "category_aliases": [
            "other account",
            "other card",
            "ticketrestaurant",
            "ticket restaurant",
            "ticket restaurants",
            "ticket",
            "buoni pasto",
            "meal vouchers",
            "meal voucher",
        ],
        "is_custom": False,
    },

    {
        "key": "glovo",
        "label": "Glovo",
        "description": "Small balance/credit account collected inside Other account.",
        "aliases": ["glovo", "glovo balance", "glovo credit"],
        "category_aliases": ["glovo", "glovo balance", "glovo credit"],
        "is_custom": False,
        "parent_key": "other_account",
    },
    {
        "key": "easypark",
        "label": "EasyPark",
        "description": "Small parking balance/credit account collected inside Other account.",
        "aliases": ["easypark", "easy park", "easypark balance", "parking credit"],
        "category_aliases": ["easypark", "easy park", "easypark balance", "parking credit"],
        "is_custom": False,
        "parent_key": "other_account",
    },
    {
        "key": PAYPAL_ACCOUNT_KEY,
        "label": "PayPal",
        "description": "PayPal wallet balance tracked as its own liquid account.",
        "aliases": [
            "paypal",
            "pay pal",
            "paypal balance",
            "pay pal balance",
            "paypal wallet",
            "pay pal wallet",
        ],
        "category_aliases": [
            "paypal",
            "pay pal",
            "paypal balance",
            "pay pal balance",
        ],
        "is_custom": False,
    },
]

# Backward compatibility for the previous v3 URL/key.
LEGACY_KEY_ALIASES = {
    "ticket_restaurant": "other_account",
}

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
    "credit",
    "card",
    "debit card",
    "credit card",
    "card credit",
    "carta credito",
    "carta di credito",
    "visa",
    "mastercard",
    *PAYPAL_CREDIT_ALIASES,
}

CREDIT_ACCOUNT_ALIASES = {
    "credit",
    "card",
    "debit card",
    "credit card",
    "card credit",
    "carta credito",
    "carta di credito",
    "visa",
    "mastercard",
    *PAYPAL_CREDIT_ALIASES,
}


def _clean_text(value) -> str:
    text = str(value or "").strip().casefold()
    if text in {"nan", "none"}:
        return ""
    return " ".join(text.split())


def _slugify(value: str) -> str:
    text = _clean_text(value)
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "custom_account"


def _split_aliases(value: str | Iterable[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        chunks = re.split(r"[,;\n]", value)
    else:
        chunks = list(value)
    seen: set[str] = set()
    aliases: list[str] = []
    for chunk in chunks:
        cleaned = _clean_text(chunk)
        if cleaned and cleaned not in seen:
            aliases.append(cleaned)
            seen.add(cleaned)
    return aliases


def _normalise_account_record(raw: dict) -> dict | None:
    label = str(raw.get("label") or raw.get("name") or "").strip()
    if not label:
        return None

    key = _slugify(str(raw.get("key") or label))
    if key in {MAIN_ACCOUNT_KEY, CREDIT_OPTION_KEY, PAYPAL_OPTION_KEY, "credit"}:
        return None

    aliases = _split_aliases(raw.get("aliases"))
    category_aliases = _split_aliases(raw.get("category_aliases") or raw.get("categories"))

    parent_key = str(raw.get("parent_key") or raw.get("parent") or "other_account").strip() or "other_account"
    if parent_key != "other_account":
        parent_key = "other_account"

    return {
        "key": key,
        "label": label,
        "description": str(raw.get("description") or "Small balance account inside Other account.").strip(),
        "aliases": aliases,
        "category_aliases": category_aliases or aliases,
        "is_custom": bool(raw.get("is_custom", True)),
        "parent_key": parent_key,
    }


def load_custom_accounts() -> list[dict]:
    if not CUSTOM_ACCOUNTS_JSON.exists():
        return []
    try:
        payload = json.loads(CUSTOM_ACCOUNTS_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    if isinstance(payload, dict):
        records = payload.get("accounts", [])
    else:
        records = payload

    accounts: list[dict] = []
    seen = {account["key"] for account in DEFAULT_AUXILIARY_ACCOUNTS}
    for raw in records if isinstance(records, list) else []:
        if not isinstance(raw, dict):
            continue
        record = _normalise_account_record(raw)
        if not record or record["key"] in seen:
            continue
        accounts.append(record)
        seen.add(record["key"])
    return accounts


def save_custom_account(label: str, description: str = "", aliases: str = "", category_aliases: str = "") -> dict | None:
    """Create or update a custom auxiliary account in data/accounts.json."""
    record = _normalise_account_record({
        "label": label,
        "description": description or "Small balance account inside Other account.",
        "parent_key": "other_account",
        "aliases": _split_aliases(aliases),
        "category_aliases": _split_aliases(category_aliases),
        "is_custom": True,
    })
    if record is None:
        return None

    DATA_DIR.mkdir(exist_ok=True, parents=True)
    accounts = load_custom_accounts()
    accounts = [account for account in accounts if account["key"] != record["key"]]
    accounts.append(record)
    CUSTOM_ACCOUNTS_JSON.write_text(
        json.dumps({"accounts": accounts}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    try:
        from money_manager.services.cache_service import notify_data_changed

        notify_data_changed()
    except Exception:
        pass
    return record


def all_auxiliary_accounts() -> list[dict]:
    return [*DEFAULT_AUXILIARY_ACCOUNTS, *load_custom_accounts()]


def auxiliary_account_keys() -> set[str]:
    return {account["key"] for account in all_auxiliary_accounts()}


def account_options_for_forms(include_credit: bool = True) -> list[dict]:
    options = [
        {
            "key": MAIN_ACCOUNT_KEY,
            "label": MAIN_ACCOUNT_LABEL,
            "description": "Blank means this movement belongs to the main bank account.",
            "value": "",
            "kind": "main",
        }
    ]
    for account in all_auxiliary_accounts():
        display_label = account["label"]
        if account.get("parent_key") == "other_account":
            display_label = f"Other account / {display_label}"
        options.append({
            **account,
            "label": display_label,
            "display_label": account["label"],
            "value": account["label"],
            "kind": "auxiliary",
        })
    if include_credit:
        options.append({
            "key": CREDIT_OPTION_KEY,
            "label": "Credit card",
            "description": "Creates a pending credit-card payment and later impacts the main account.",
            "value": "credit",
            "kind": "credit",
        })
    return options


def account_options_for_analysis() -> list[dict]:
    return all_auxiliary_accounts()


def category_aliases_by_key() -> dict[str, set[str]]:
    mapping: dict[str, set[str]] = {}
    for account in all_auxiliary_accounts():
        aliases = set(_split_aliases(account.get("category_aliases")))
        aliases.add(_clean_text(account.get("label", "")))
        aliases.update(_split_aliases(account.get("aliases")))
        aliases.add(_clean_text(account.get("key", "")))
        mapping[account["key"]] = {alias for alias in aliases if alias}
    return mapping


def _alias_to_key() -> dict[str, str]:
    mapping = {alias.casefold(): MAIN_ACCOUNT_KEY for alias in MAIN_ACCOUNT_ALIASES}
    for legacy_key, real_key in LEGACY_KEY_ALIASES.items():
        mapping[legacy_key.casefold()] = real_key
    for account in all_auxiliary_accounts():
        mapping[_clean_text(account["key"])] = account["key"]
        mapping[_clean_text(account["label"])] = account["key"]
        for alias in account.get("aliases", []):
            mapping[_clean_text(alias)] = account["key"]
    return mapping


def normalize_account_key(value: str | None) -> str:
    """Return the configured account key for a raw CSV account value."""
    text = _clean_text(value)
    return _alias_to_key().get(text, MAIN_ACCOUNT_KEY)


def is_main_account_value(value: str | None) -> bool:
    """True only for blank/Main/Credit aliases, not PayPal balance or unknown accounts."""
    return _clean_text(value) in MAIN_ACCOUNT_ALIASES


def account_parent_key(key: str | None) -> str:
    canonical = LEGACY_KEY_ALIASES.get(str(key or ""), str(key or ""))
    for account in all_auxiliary_accounts():
        if account["key"] == canonical:
            return str(account.get("parent_key") or "")
    return ""


def account_label_for_key(key: str | None) -> str:
    canonical = LEGACY_KEY_ALIASES.get(str(key or ""), str(key or ""))
    if canonical == MAIN_ACCOUNT_KEY:
        return MAIN_ACCOUNT_LABEL
    for account in all_auxiliary_accounts():
        if account["key"] == canonical:
            return account["label"]
    return MAIN_ACCOUNT_LABEL


def account_description_for_key(key: str | None) -> str:
    canonical = LEGACY_KEY_ALIASES.get(str(key or ""), str(key or ""))
    if canonical == MAIN_ACCOUNT_KEY:
        return "Blank account value. Used for ordinary movements in the tracked main net."
    for account in all_auxiliary_accounts():
        if account["key"] == canonical:
            return account.get("description", "")
    return ""


def account_label_for_value(value: str | None) -> str:
    raw = _clean_text(value)
    if raw in PAYPAL_CREDIT_ALIASES:
        return "PayPal credit route"
    if raw in CREDIT_ACCOUNT_ALIASES:
        return "Credit card"
    return account_label_for_key(normalize_account_key(value))


def is_auxiliary_account(value: str | None) -> bool:
    return normalize_account_key(value) in auxiliary_account_keys()


# Backward-compatible names used by older modules.  Use functions above for
# current screens so custom account additions show without restarting imports.
AUXILIARY_ACCOUNTS = DEFAULT_AUXILIARY_ACCOUNTS
AUXILIARY_ACCOUNT_KEYS = {account["key"] for account in DEFAULT_AUXILIARY_ACCOUNTS}
ACCOUNT_OPTIONS = account_options_for_forms()
