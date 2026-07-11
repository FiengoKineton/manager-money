from __future__ import annotations

r"""
Backfill old Money Manager CSV/JSON rows to the current account/payment/receipt model.

This tool is intentionally data-folder based. It works on a decrypted user_data folder
and does not need the Flask app or the vault to be running.

Use from the repo root while the app is closed:

  .venv\Scripts\python.exe tools\migrate_legacy_data_to_current_logic_v2.py --data-dir MoneyManagerData\data\users\<user_id> --dry-run
  .venv\Scripts\python.exe tools\migrate_legacy_data_to_current_logic_v2.py --data-dir MoneyManagerData\data\users\<user_id> --apply

It also accepts a direct flat user_data folder:

  .venv\Scripts\python.exe tools\migrate_legacy_data_to_current_logic_v2.py --data-dir MoneyManagerData\data\users\<user_id>\user_data --apply
"""

import argparse
import csv
import json
import math
import re
import shutil
import uuid
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

try:
    from money_manager.domain.constants import (
        ACCOUNT_LEDGER_FIELDS,
        CREDIT_SETTLEMENT_FIELDS,
        DEBT_FIELDS,
        INVESTMENT_ASSET_FIELDS,
        INTERNAL_TRANSFER_FIELDS,
        PAYABLE_FIELDS,
        PENDING_FIELDS,
        RECEIVABLE_FIELDS,
        RECURRING_FIELDS,
        TRANSACTION_FIELDS,
    )
except Exception:  # pragma: no cover - fallback only for emergency standalone use
    TRANSACTION_FIELDS = [
        "id", "transaction_uid", "date", "category", "sub_category", "amount",
        "original_amount", "original_currency", "exchange_rate_to_eur", "exchange_correction_to_eur", "exchange_effective_rate_to_eur",
        "account", "account_id", "account_key_snapshot", "account_name_snapshot", "account_due_day_snapshot",
        "payment_method", "payment_method_id", "payment_method_name_snapshot", "payment_channel_method_id_snapshot", "payment_channel_name_snapshot",
        "funding_account_id_snapshot", "funding_account_name_snapshot", "settlement_account_id_snapshot", "settlement_account_name_snapshot",
        "liability_account_id_snapshot", "liability_account_name_snapshot", "settlement_mode_snapshot", "payment_due_date_snapshot",
        "payment_due_day_snapshot", "payment_statement_period_snapshot", "payment_resolution_json", "ledger_group_id", "ledger_status",
        "contact_id", "contact_name", "iban_snapshot", "bic_swift_snapshot", "bank_name_snapshot", "transfer_reference", "transfer_status",
        "description", "created_at",
    ]
    PENDING_FIELDS = ["id", "type", "date_due", "amount", "category", "account", "description", "status", "source", "source_id", "source_occurrence_date", "pending_kind", "account_key", "account_label", "statement_month", "date_charge", "account_id", "account_name_snapshot", "payment_method_id", "payment_method_name_snapshot", "payment_resolution_template_json"]
    RECURRING_FIELDS = ["id", "name", "type", "amount", "frequency", "day_of_month", "category", "account", "start_date", "end_date", "max_occurrences", "last_generated", "account_id", "account_name_snapshot", "payment_method_id", "payment_method_name_snapshot", "payment_resolution_template_json"]
    DEBT_FIELDS = ["id", "name", "creditor", "original_amount", "remaining_amount", "category", "account", "start_date", "due_date", "description", "status", "created_at", "closed_at", "account_id", "account_name_snapshot", "preferred_payment_method_id", "preferred_payment_method_name_snapshot"]
    PAYABLE_FIELDS = ["id", "name", "payee", "original_amount", "remaining_amount", "category", "account", "start_date", "due_date", "description", "status", "created_at", "closed_at", "account_id", "account_name_snapshot", "preferred_payment_method_id", "preferred_payment_method_name_snapshot"]
    RECEIVABLE_FIELDS = ["id", "name", "debtor", "original_amount", "remaining_amount", "account", "start_date", "due_date", "description", "status", "linked_expense_transaction_id", "created_at", "closed_at", "account_id", "account_name_snapshot", "preferred_payment_method_id", "preferred_payment_method_name_snapshot"]
    INVESTMENT_ASSET_FIELDS = ["id", "symbol", "label", "allocation_pct", "currency", "active", "created_at", "funding_account_id", "funding_account_name_snapshot", "payment_method_id", "payment_method_name_snapshot"]
    INTERNAL_TRANSFER_FIELDS = ["id", "transfer_uid", "date", "from_account", "to_account", "from_account_id", "from_account_name_snapshot", "to_account_id", "to_account_name_snapshot", "amount", "fee_amount", "fee_payment_method_id", "fee_payment_method_name_snapshot", "ledger_group_id", "status", "transfer_kind", "metadata_json", "description", "created_at", "updated_at"]
    ACCOUNT_LEDGER_FIELDS = ["id", "ledger_group_id", "transaction_uid", "transaction_type", "transaction_id", "source_kind", "source_id", "date", "effective_date", "account_id", "account_name_snapshot", "counterparty_account_id", "counterparty_account_name_snapshot", "payment_method_id", "payment_method_name_snapshot", "movement_kind", "direction", "amount", "currency", "signed_amount", "status", "is_void", "voided_by_ledger_group_id", "created_from_resolution_json", "notes", "created_at"]
    CREDIT_SETTLEMENT_FIELDS = ["id", "settlement_uid", "payment_method_id", "payment_method_name_snapshot", "liability_account_id", "liability_account_name_snapshot", "settlement_account_id", "settlement_account_name_snapshot", "statement_period", "due_date", "amount", "currency", "status", "ledger_group_id", "pending_id", "executed_transaction_uid", "created_from_ledger_group_ids_json", "created_at", "updated_at", "executed_at", "notes"]

MAIN_ACCOUNT = "main_bank"
MAIN_DEBIT = "main_bank_debit_card"
MAIN_TRANSFER = "main_bank_transfer"
CREDIT_ACCOUNT = "credit_card"
CREDIT_METHOD = "credit_card"
PAYPAL_CREDIT_METHOD = "paypal_via_credit_card"
PAYPAL_BALANCE_METHOD = "paypal_balance"
DEFAULT_DUE_DAY = 15

SPECIAL_ACCOUNT_METHODS = {
    "cash": ("cash_flow", "cash"),
    "cash_flow": ("cash_flow", "cash"),
    "contanti": ("cash_flow", "cash"),
    "pre_paid_card": ("pre_paid_card", "pre_paid_card"),
    "pre-paid card": ("pre_paid_card", "pre_paid_card"),
    "prepaid card": ("pre_paid_card", "pre_paid_card"),
    "pre paid card": ("pre_paid_card", "pre_paid_card"),
    "prepaid": ("pre_paid_card", "pre_paid_card"),
    "postepay": ("pre_paid_card", "pre_paid_card"),
    "edenred": ("edenred", "edenred"),
    "eden red": ("edenred", "edenred"),
    "paypal": ("paypal", PAYPAL_BALANCE_METHOD),
    "pay pal": ("paypal", PAYPAL_BALANCE_METHOD),
    "glovo": ("glovo", "glovo"),
    "easypark": ("easypark", "easypark"),
    "easy park": ("easypark", "easypark"),
    "lost": ("lost", "lost"),
}

CREDIT_ALIASES = {"credit", "credit card", "credit cards", "card credit", "carta credito", "carta di credito", "credit_card"}
PAYPAL_CREDIT_ALIASES = {"paypal_credit", "paypal credit", "pay pal credit", "paypal card", "pay pal card"}
MAIN_ALIASES = {"", "auto", "main", "bank", "main bank", "main bank account", "bank account", "card", "debit", "debit card", "main_bank"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean(value: Any) -> str:
    text = str(value or "").strip().casefold()
    text = " ".join(text.split())
    return "" if text in {"nan", "none", "null"} else text


def label(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.casefold() in {"nan", "none", "null"} else " ".join(text.split())


def slug(value: Any) -> str:
    text = clean(value)
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_")


def money(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    text = str(value).strip().replace("€", "").replace(" ", "").replace(",", ".")
    try:
        out = float(text)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(out) or math.isinf(out):
        return 0.0
    return round(out, 2)


def fmt(value: Any) -> str:
    return f"{money(value):.2f}"


def parse_date(value: Any) -> date:
    text = str(value or "").strip()
    if not text:
        return date.today()
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return date.today()


def add_month(year: int, month: int, offset: int = 1) -> tuple[int, int]:
    idx = year * 12 + (month - 1) + offset
    return idx // 12, idx % 12 + 1


def due_date_for(tx_date: str, due_day: int = DEFAULT_DUE_DAY) -> str:
    d = parse_date(tx_date)
    y, m = add_month(d.year, d.month, 1)
    import calendar
    return date(y, m, min(due_day, calendar.monthrange(y, m)[1])).isoformat()


def statement_period_for(tx_date: str) -> str:
    d = parse_date(tx_date)
    return f"{d.year:04d}-{d.month:02d}"


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return deepcopy(default)
    try:
        with path.open("r", encoding="utf-8-sig") as fh:
            return json.load(fh)
    except Exception:
        return deepcopy(default)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False, sort_keys=False)
        fh.write("\n")
    tmp.replace(path)


def read_csv(path: Path, fields: list[str]) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = []
        for raw in reader:
            row = {field: str(raw.get(field, "") or "") for field in fields}
            for key, value in raw.items():
                if key is not None and key not in row:
                    row[key] = str(value or "")
            rows.append(row)
        return rows


def write_csv(path: Path, fields: list[str], rows: list[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    extra = []
    seen = set(fields)
    for row in rows:
        for key in row.keys():
            if key not in seen:
                extra.append(key)
                seen.add(key)
    fieldnames = [*fields, *extra]
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})
    tmp.replace(path)


def find_data_dir(raw: str) -> Path:
    path = Path(raw).expanduser().resolve()
    if (path / "expenses.csv").exists() or (path / "accounts.json").exists():
        return path
    if (path / "user_data" / "expenses.csv").exists() or (path / "user_data" / "accounts.json").exists():
        return path / "user_data"
    raise SystemExit(f"Could not find a flat user_data folder under: {path}")


def build_maps(accounts_payload: Mapping[str, Any], methods_payload: Mapping[str, Any]) -> dict[str, Any]:
    accounts = [a for a in accounts_payload.get("accounts", []) if isinstance(a, Mapping)]
    methods = [m for m in methods_payload.get("payment_methods", []) if isinstance(m, Mapping)]
    accounts_by_key = {str(a.get("key") or a.get("id") or ""): dict(a) for a in accounts}
    methods_by_id = {str(m.get("id") or ""): dict(m) for m in methods}
    account_aliases: dict[str, str] = {}
    method_aliases: dict[str, str] = {}
    for account in accounts:
        key = str(account.get("key") or account.get("id") or "")
        for value in [account.get("id"), account.get("key"), account.get("label"), account.get("name"), *(account.get("aliases") or [])]:
            c = clean(value)
            if c:
                account_aliases[c] = key
    for method in methods:
        mid = str(method.get("id") or "")
        for value in [method.get("id"), method.get("name"), *(method.get("aliases") or [])]:
            c = clean(value)
            if c:
                method_aliases[c] = mid
    return {"accounts": accounts_by_key, "methods": methods_by_id, "account_aliases": account_aliases, "method_aliases": method_aliases}


def account_name(maps: Mapping[str, Any], account_id: str) -> str:
    account = maps["accounts"].get(account_id, {})
    return str(account.get("label") or account.get("name") or account_id)


def method_name(maps: Mapping[str, Any], method_id: str) -> str:
    method = maps["methods"].get(method_id, {})
    return str(method.get("name") or method_id)


def ensure_current_account_payment_config(data_dir: Path, report: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    accounts_payload = read_json(data_dir / "accounts.json", {"schema_version": 3, "accounts": []})
    methods_payload = read_json(data_dir / "payment_methods.json", {"schema_version": 1, "payment_methods": []})
    accounts = [dict(a) for a in accounts_payload.get("accounts", []) if isinstance(a, Mapping)]
    methods = [dict(m) for m in methods_payload.get("payment_methods", []) if isinstance(m, Mapping)]

    def ensure_account(raw: Mapping[str, Any]) -> None:
        key = str(raw.get("key") or raw.get("id") or "")
        for existing in accounts:
            if str(existing.get("key") or existing.get("id") or "") == key:
                for k, v in raw.items():
                    if k not in existing or existing.get(k) in ("", None, [], {}):
                        existing[k] = deepcopy(v)
                return
        accounts.append(dict(raw))
        report["accounts_added"].append(key)

    def ensure_method(raw: Mapping[str, Any], *, force_active: bool = False, force_default: bool | None = None) -> None:
        mid = str(raw.get("id") or "")
        for existing in methods:
            if str(existing.get("id") or "") == mid:
                changed = False
                for k, v in raw.items():
                    if k in {"aliases", "metadata", "legacy", "rules"}:
                        if not isinstance(existing.get(k), type(v)) or not existing.get(k):
                            existing[k] = deepcopy(v); changed = True
                    elif existing.get(k) in ("", None):
                        existing[k] = deepcopy(v); changed = True
                if force_active and (existing.get("is_archived") or not existing.get("is_active", True)):
                    existing["is_active"] = True
                    existing["is_archived"] = False
                    existing["archived_at"] = ""
                    existing.setdefault("legacy", {})["reactivated_by"] = "migrate_legacy_data_to_current_logic_v2"
                    changed = True
                if force_default is not None and bool(existing.get("is_default")) != force_default:
                    existing["is_default"] = force_default
                    changed = True
                if changed:
                    existing["updated_at"] = now()
                    report["payment_methods_repaired"].append(mid)
                return
        method = dict(raw)
        if force_active:
            method["is_active"] = True; method["is_archived"] = False; method["archived_at"] = ""
        if force_default is not None:
            method["is_default"] = force_default
        methods.append(method)
        report["payment_methods_added"].append(mid)

    ensure_account({
        "id": CREDIT_ACCOUNT, "key": CREDIT_ACCOUNT, "name": "Credit Card", "label": "Credit Card",
        "account_kind": "credit_card_liability", "type": "credit_card_liability", "currency": "EUR",
        "main_net_policy": "credit_pending", "is_liability": True, "is_financial_center": False,
        "is_current_account": False, "is_dependent_account": False, "parent_account_id": "", "parent_key": "",
        "is_active": True, "is_closed": False, "display_order": 90,
        "aliases": ["credit", "credit card", "credit cards", "card credit", "carta credito", "carta di credito", "credit_card"],
        "category_aliases": ["credit", "credit card", "credit cards", "card credit", "carta credito", "carta di credito"],
        "category_match_enabled": True, "category_match_mode": "credit_pending", "due_day": DEFAULT_DUE_DAY,
        "statement_day": None, "payment_logic": {"schema_version": 1, "mode": "credit_statement", "default_method": "credit", "allowed_methods": ["credit"], "can_pay_from": True, "affects_main_net_now": False, "creates_pending": True},
    })

    ensure_method({
        "id": MAIN_DEBIT, "name": "Debit Card", "method_type": "debit_card", "settlement_mode": "immediate",
        "linked_account_id": MAIN_ACCOUNT, "funding_account_id": MAIN_ACCOUNT, "settlement_account_id": MAIN_ACCOUNT,
        "liability_account_id": "", "delegates_to_payment_method_id": "", "display_order": 0,
        "aliases": ["main_bank", "main bank account", "main debit", "main debit card", "debit", "debit card", "card", "bancomat"],
        "rules": {"due_day": None, "statement_day": None, "settlement_day_policy": "next_month", "allow_manual_due_date": True},
        "metadata": {"auto_default": True, "visible_card": True}, "legacy": {"migration_rule": "current_default_debit_card"},
    }, force_active=True, force_default=True)
    # The debit card must be the implicit/default payment route for a first-level bank account.
    for method in methods:
        if str(method.get("id") or "") != MAIN_DEBIT and bool(method.get("is_default")):
            method["is_default"] = False
            method["updated_at"] = now()
            report["payment_methods_repaired"].append(str(method.get("id") or ""))

    ensure_method({
        "id": MAIN_TRANSFER, "name": "Main bank account", "method_type": "bank_transfer", "settlement_mode": "immediate",
        "linked_account_id": MAIN_ACCOUNT, "funding_account_id": MAIN_ACCOUNT, "settlement_account_id": MAIN_ACCOUNT,
        "liability_account_id": "", "delegates_to_payment_method_id": "", "display_order": 5,
        "aliases": ["main", "bank", "main bank", "bank transfer", "bonifico", "main bank account"],
        "rules": {"due_day": None, "statement_day": None, "settlement_day_policy": "next_month", "allow_manual_due_date": True},
        "metadata": {"auto_default": True, "visible_card": False}, "legacy": {"migration_rule": "current_main_bank_transfer"},
    }, force_active=True, force_default=False)

    ensure_method({
        "id": CREDIT_METHOD, "name": "Credit Card", "method_type": "credit_card", "settlement_mode": "delayed",
        "linked_account_id": "", "funding_account_id": MAIN_ACCOUNT, "settlement_account_id": MAIN_ACCOUNT,
        "liability_account_id": CREDIT_ACCOUNT, "delegates_to_payment_method_id": "", "display_order": 60,
        "aliases": ["credit", "credit card", "credit cards", "card credit", "carta credito", "carta di credito"],
        "rules": {"due_day": DEFAULT_DUE_DAY, "statement_day": None, "settlement_day_policy": "next_month", "allow_manual_due_date": True},
        "metadata": {"visible_card": True}, "legacy": {"migration_rule": "current_credit_card_delayed"},
    }, force_active=True, force_default=False)

    ensure_method({
        "id": PAYPAL_CREDIT_METHOD, "name": "PayPal via Credit Card", "method_type": "wallet_linked_card", "settlement_mode": "delegated",
        "linked_account_id": "paypal", "funding_account_id": "", "settlement_account_id": "", "liability_account_id": "",
        "delegates_to_payment_method_id": CREDIT_METHOD, "display_order": 70,
        "aliases": ["paypal_credit", "paypal credit", "pay pal credit", "paypal card", "pay pal card"],
        "rules": {"due_day": None, "statement_day": None, "settlement_day_policy": "next_month", "allow_manual_due_date": True},
        "metadata": {"visible_card": True}, "legacy": {"migration_rule": "current_paypal_via_credit_card"},
    }, force_active=True, force_default=False)

    accounts_payload["schema_version"] = 3
    accounts_payload["accounts"] = accounts
    accounts_payload["updated_at"] = now()
    methods_payload["schema_version"] = 1
    methods_payload["payment_methods"] = methods
    methods_payload["updated_at"] = now()
    return accounts_payload, methods_payload


def choose_route(row: Mapping[str, Any], tx_type: str, maps: Mapping[str, Any]) -> dict[str, Any]:
    # Existing stable payment method wins unless it points to a missing method.
    existing_mid = str(row.get("payment_method_id") or "").strip()
    if existing_mid and existing_mid in maps["methods"]:
        method_id = existing_mid
    else:
        raw_method = clean(row.get("payment_method") or "")
        raw_account_id = clean(row.get("account_id") or row.get("account_key_snapshot") or "")
        raw_account = clean(row.get("account") or "")
        cat = clean(row.get("category") or "")
        sub = clean(row.get("sub_category") or "")
        desc = clean(row.get("description") or "")
        text = " ".join(x for x in [raw_account, raw_account_id, raw_method, cat, sub, desc] if x)

        if raw_method and raw_method in maps["method_aliases"]:
            method_id = maps["method_aliases"][raw_method]
        elif raw_account_id in PAYPAL_CREDIT_ALIASES or raw_account in PAYPAL_CREDIT_ALIASES:
            method_id = PAYPAL_CREDIT_METHOD
        elif raw_account_id in CREDIT_ALIASES or raw_account in CREDIT_ALIASES:
            method_id = CREDIT_METHOD
        elif cat in {"credit cards", "credit card", "carta credito"} and not looks_like_credit_settlement(row):
            method_id = CREDIT_METHOD
        elif raw_account_id in SPECIAL_ACCOUNT_METHODS:
            method_id = SPECIAL_ACCOUNT_METHODS[raw_account_id][1]
        elif raw_account in SPECIAL_ACCOUNT_METHODS:
            method_id = SPECIAL_ACCOUNT_METHODS[raw_account][1]
        elif raw_account_id and raw_account_id in maps["account_aliases"]:
            account_id = maps["account_aliases"][raw_account_id]
            method_id = first_method_for_account(account_id, maps, tx_type=tx_type)
        elif raw_account and raw_account in maps["account_aliases"] and raw_account not in MAIN_ALIASES:
            account_id = maps["account_aliases"][raw_account]
            method_id = first_method_for_account(account_id, maps, tx_type=tx_type)
        else:
            # User rule: old non-credit rows with missing bank/card info used the debit card of Mediolanum/Main.
            method_id = MAIN_DEBIT if tx_type == "expense" else MAIN_TRANSFER

    # Current settlement semantics.
    method = maps["methods"].get(method_id, {})
    mtype = str(method.get("method_type") or "")
    mode = str(method.get("settlement_mode") or "")
    if method_id == PAYPAL_CREDIT_METHOD:
        channel_id = PAYPAL_CREDIT_METHOD
        channel_name = method_name(maps, PAYPAL_CREDIT_METHOD)
        base = maps["methods"].get(CREDIT_METHOD, {})
        return route_from_method(CREDIT_METHOD, base, tx_type, row, maps, channel_id=channel_id, channel_name=channel_name, linked_account_id="paypal")
    return route_from_method(method_id, method, tx_type, row, maps)


def first_method_for_account(account_id: str, maps: Mapping[str, Any], tx_type: str = "expense") -> str:
    preferred = []
    account = maps["accounts"].get(account_id, {})
    kind = str(account.get("account_kind") or account.get("type") or "")
    if kind == "current_account":
        preferred = ["debit_card", "bank_transfer"] if tx_type == "expense" else ["bank_transfer", "debit_card"]
    elif kind == "credit_card_liability":
        preferred = ["credit_card"]
    elif kind == "cash":
        preferred = ["cash"]
    elif kind == "prepaid_balance":
        preferred = ["prepaid_card"]
    elif kind == "meal_voucher":
        preferred = ["meal_voucher"]
    elif kind in {"wallet_balance", "dependent_wallet"}:
        preferred = ["wallet_balance"]
    for wanted in preferred:
        for mid, method in maps["methods"].items():
            if clean(method.get("method_type")) != wanted:
                continue
            if account_id in {str(method.get("linked_account_id") or ""), str(method.get("funding_account_id") or ""), str(method.get("settlement_account_id") or ""), str(method.get("liability_account_id") or "")}:
                return mid
    return MAIN_DEBIT if tx_type == "expense" else MAIN_TRANSFER


def route_from_method(method_id: str, method: Mapping[str, Any], tx_type: str, row: Mapping[str, Any], maps: Mapping[str, Any], *, channel_id: str = "", channel_name: str = "", linked_account_id: str = "") -> dict[str, Any]:
    amount = money(row.get("amount"))
    tx_date = str(row.get("date") or date.today().isoformat())[:10]
    mtype = str(method.get("method_type") or "")
    mode = str(method.get("settlement_mode") or "")
    funding = str(method.get("funding_account_id") or "")
    linked = linked_account_id or str(method.get("linked_account_id") or "")
    settlement = str(method.get("settlement_account_id") or funding or linked or "")
    liability = str(method.get("liability_account_id") or "")
    due_day = int((method.get("rules") or {}).get("due_day") or DEFAULT_DUE_DAY) if isinstance(method.get("rules"), Mapping) else DEFAULT_DUE_DAY

    if tx_type == "income":
        account_id = linked or funding or settlement or account_from_row(row, maps) or MAIN_ACCOUNT
        signed = amount
        movement_kind = "income_cash_in"
        direction = "in"
        due = ""; statement = ""; liability = ""
    elif tx_type == "investment":
        account_id = funding or settlement or account_from_row(row, maps) or MAIN_ACCOUNT
        signed = amount if clean(row.get("category")) == "dividend" else -amount
        movement_kind = "income_cash_in" if signed >= 0 else "investment_cash_out"
        direction = "in" if signed >= 0 else "out"
        due = ""; statement = ""; liability = ""
    elif mode == "delayed" or mtype == "credit_card":
        account_id = liability or CREDIT_ACCOUNT
        signed = -amount
        movement_kind = "credit_liability_increase"
        direction = "liability_increase"
        due = due_date_for(tx_date, due_day=due_day)
        statement = statement_period_for(tx_date)
        funding = funding or MAIN_ACCOUNT
        settlement = settlement or funding
        liability = account_id
    elif looks_like_credit_settlement(row):
        # Statement-payment rows are legacy cash payments to the credit-card bill.
        # They are kept as expense CSV rows for historical compatibility, but the ledger
        # gets a main-bank cash-out and a liability decrease.
        account_id = MAIN_ACCOUNT
        signed = -amount
        movement_kind = "credit_statement_cash_out"
        direction = "out"
        due = ""; statement = statement_period_for(tx_date); liability = CREDIT_ACCOUNT; settlement = MAIN_ACCOUNT; funding = MAIN_ACCOUNT
    elif mode == "stored_balance" or mtype in {"cash", "prepaid_card", "wallet_balance", "meal_voucher", "investment_cash_transfer"}:
        account_id = linked or funding or settlement or account_from_row(row, maps) or MAIN_ACCOUNT
        signed = -amount
        movement_kind = "expense_cash_out" if mtype != "investment_cash_transfer" else "investment_cash_out"
        direction = "out"
        due = ""; statement = ""; funding = account_id; settlement = account_id
    else:
        account_id = funding or settlement or linked or account_from_row(row, maps) or MAIN_ACCOUNT
        signed = -amount
        movement_kind = "expense_cash_out"
        direction = "out"
        due = ""; statement = ""; funding = account_id; settlement = account_id

    return {
        "method_id": method_id,
        "method_name": method_name(maps, method_id),
        "channel_id": channel_id or method_id,
        "channel_name": channel_name or method_name(maps, method_id),
        "account_id": account_id,
        "account_name": account_name(maps, account_id),
        "funding_account_id": funding,
        "funding_account_name": account_name(maps, funding) if funding else "",
        "settlement_account_id": settlement,
        "settlement_account_name": account_name(maps, settlement) if settlement else "",
        "liability_account_id": liability,
        "liability_account_name": account_name(maps, liability) if liability else "",
        "settlement_mode": mode or "immediate",
        "due_date": due,
        "due_day": str(due_day) if due else "",
        "statement_period": statement,
        "movement_kind": movement_kind,
        "direction": direction,
        "signed_amount": signed,
        "amount": amount,
    }


def account_from_row(row: Mapping[str, Any], maps: Mapping[str, Any]) -> str:
    for key in [row.get("account_id"), row.get("account_key_snapshot"), row.get("account")]:
        c = clean(key)
        if c in maps["account_aliases"]:
            return maps["account_aliases"][c]
    return MAIN_ACCOUNT


def looks_like_credit_settlement(row: Mapping[str, Any]) -> bool:
    text = clean(" ".join(str(row.get(k, "") or "") for k in ("category", "sub_category", "description")))
    account = clean(row.get("account") or row.get("account_id") or "")
    return (
        "statement payment" in text
        or "credit card payment" in text
        or "credit statement payment" in text
        or "settlement" in text
        or (account in PAYPAL_CREDIT_ALIASES and "payment" in text)
    )


def payment_resolution_json(tx_type: str, row: Mapping[str, Any], route: Mapping[str, Any], ledger_group_id: str) -> str:
    payload = {
        "ok": True,
        "transaction_type": tx_type,
        "amount": route["amount"],
        "currency": "EUR",
        "transaction_date": str(row.get("date") or "")[:10],
        "ledger_group_id": ledger_group_id,
        "payment_method_id": route["method_id"],
        "payment_method_name_snapshot": route["method_name"],
        "payment_channel_method_id_snapshot": route["channel_id"],
        "payment_channel_name_snapshot": route["channel_name"],
        "account_id": route["account_id"],
        "account_name_snapshot": route["account_name"],
        "funding_account_id": route["funding_account_id"],
        "settlement_account_id": route["settlement_account_id"],
        "liability_account_id": route["liability_account_id"],
        "settlement_mode": route["settlement_mode"],
        "due_date": route["due_date"],
        "due_day_snapshot": route["due_day"] or None,
        "statement_period": route["statement_period"],
        "movement_count": 1,
        "warnings": ["legacy row backfilled by migrate_legacy_data_to_current_logic_v2"],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def migrate_transactions(data_dir: Path, maps: Mapping[str, Any], report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    tx_index: dict[str, dict[str, Any]] = {}
    for tx_type, filename in [("expense", "expenses.csv"), ("income", "incomes.csv"), ("investment", "investments.csv")]:
        path = data_dir / filename
        rows = read_csv(path, TRANSACTION_FIELDS)
        changed = 0
        for row in rows:
            tx_id = str(row.get("id") or "").strip()
            if not tx_id:
                continue
            uid = row.get("transaction_uid") or f"{tx_type}:{tx_id}"
            row["transaction_uid"] = uid
            route = choose_route(row, tx_type, maps)
            ledger_group = row.get("ledger_group_id") or f"lg_mig_{uuid.uuid5(uuid.NAMESPACE_URL, uid).hex}"
            before = dict(row)

            # Stable current metadata. Keep the legacy display account text if it already exists;
            # current columns carry the real route.
            row["account_id"] = row.get("account_id") or route["account_id"]
            row["account_key_snapshot"] = row.get("account_key_snapshot") or route["account_id"]
            row["account_name_snapshot"] = row.get("account_name_snapshot") or route["account_name"]
            if not row.get("account") and route["account_id"] != MAIN_ACCOUNT and not (tx_type == "expense" and route["method_id"] == CREDIT_METHOD and clean(row.get("category")) == "credit cards"):
                row["account"] = route["account_name"]
            row["payment_method_id"] = row.get("payment_method_id") or route["method_id"]
            row["payment_method"] = row.get("payment_method") or route["method_name"]
            row["payment_method_name_snapshot"] = row.get("payment_method_name_snapshot") or route["method_name"]
            row["payment_channel_method_id_snapshot"] = row.get("payment_channel_method_id_snapshot") or route["channel_id"]
            row["payment_channel_name_snapshot"] = row.get("payment_channel_name_snapshot") or route["channel_name"]
            row["funding_account_id_snapshot"] = row.get("funding_account_id_snapshot") or route["funding_account_id"]
            row["funding_account_name_snapshot"] = row.get("funding_account_name_snapshot") or route["funding_account_name"]
            row["settlement_account_id_snapshot"] = row.get("settlement_account_id_snapshot") or route["settlement_account_id"]
            row["settlement_account_name_snapshot"] = row.get("settlement_account_name_snapshot") or route["settlement_account_name"]
            row["liability_account_id_snapshot"] = row.get("liability_account_id_snapshot") or route["liability_account_id"]
            row["liability_account_name_snapshot"] = row.get("liability_account_name_snapshot") or route["liability_account_name"]
            row["settlement_mode_snapshot"] = row.get("settlement_mode_snapshot") or route["settlement_mode"]
            row["payment_due_date_snapshot"] = row.get("payment_due_date_snapshot") or route["due_date"]
            row["payment_due_day_snapshot"] = row.get("payment_due_day_snapshot") or route["due_day"]
            row["payment_statement_period_snapshot"] = row.get("payment_statement_period_snapshot") or route["statement_period"]
            row["ledger_group_id"] = ledger_group
            row["ledger_status"] = row.get("ledger_status") or "posted"
            row["payment_resolution_json"] = row.get("payment_resolution_json") or payment_resolution_json(tx_type, row, route, ledger_group)
            row["created_at"] = row.get("created_at") or now()

            tx_index[uid] = {"type": tx_type, "row": dict(row), "route": route, "ledger_group_id": ledger_group}
            if row != before:
                changed += 1
        if changed:
            report["transaction_rows_changed"][filename] = changed
        write_csv(path, TRANSACTION_FIELDS, rows)
    return tx_index


def migrate_pending_recurring(data_dir: Path, maps: Mapping[str, Any], report: dict[str, Any]) -> None:
    for filename, fields, kind in [("pending.csv", PENDING_FIELDS, "pending"), ("recurring.csv", RECURRING_FIELDS, "recurring")]:
        rows = read_csv(data_dir / filename, fields)
        changed = 0
        for row in rows:
            tx_type = clean(row.get("type") or "expense") or "expense"
            fake = {
                "date": row.get("date_due") or row.get("start_date") or date.today().isoformat(),
                "amount": row.get("amount"),
                "category": row.get("category"),
                "account": row.get("account"),
                "account_id": row.get("account_id"),
                "payment_method_id": row.get("payment_method_id"),
                "description": row.get("description") or row.get("name"),
            }
            route = choose_route(fake, tx_type, maps)
            before = dict(row)
            row["account_id"] = row.get("account_id") or route["account_id"]
            row["account_name_snapshot"] = row.get("account_name_snapshot") or route["account_name"]
            row["payment_method_id"] = row.get("payment_method_id") or route["method_id"]
            row["payment_method_name_snapshot"] = row.get("payment_method_name_snapshot") or route["method_name"]
            template = {
                "schema_version": 1,
                "transaction_type": tx_type,
                "account_id": route["account_id"],
                "account_name_snapshot": route["account_name"],
                "payment_method_id": route["method_id"],
                "payment_method_name_snapshot": route["method_name"],
                "settlement_mode": route["settlement_mode"],
                "funding_account_id": route["funding_account_id"],
                "settlement_account_id": route["settlement_account_id"],
                "liability_account_id": route["liability_account_id"],
                "backfilled_by": "migrate_legacy_data_to_current_logic_v2",
            }
            row["payment_resolution_template_json"] = row.get("payment_resolution_template_json") or json.dumps(template, ensure_ascii=False, sort_keys=True)
            if kind == "pending":
                row["pending_kind"] = row.get("pending_kind") or ("credit_statement" if route["settlement_mode"] == "delayed" or route["liability_account_id"] else "manual")
                row["account_key"] = row.get("account_key") or route["account_id"]
                row["account_label"] = row.get("account_label") or route["account_name"]
                row["date_charge"] = row.get("date_charge") or (fake["date"] if route["settlement_mode"] == "delayed" else "")
                row["statement_month"] = row.get("statement_month") or route["statement_period"]
            if row != before:
                changed += 1
        if changed:
            report[f"{kind}_rows_changed"] = changed
        write_csv(data_dir / filename, fields, rows)


def migrate_support_tables(data_dir: Path, maps: Mapping[str, Any], report: dict[str, Any]) -> None:
    specs = [
        ("debts.csv", DEBT_FIELDS, "preferred_payment_method_id"),
        ("payables.csv", PAYABLE_FIELDS, "preferred_payment_method_id"),
        ("receivables.csv", RECEIVABLE_FIELDS, "preferred_payment_method_id"),
        ("investment_assets.csv", INVESTMENT_ASSET_FIELDS, "payment_method_id"),
    ]
    for filename, fields, method_field in specs:
        rows = read_csv(data_dir / filename, fields)
        changed = 0
        for row in rows:
            before = dict(row)
            route = choose_route({"type": "expense", "amount": row.get("remaining_amount") or row.get("original_amount"), "account": row.get("account"), "account_id": row.get("account_id")}, "expense", maps)
            if filename == "receivables.csv":
                # money owed to the user normally arrives into the main bank unless an account was explicit
                route = choose_route({"type": "income", "amount": row.get("remaining_amount") or row.get("original_amount"), "account": row.get("account"), "account_id": row.get("account_id")}, "income", maps)
            row["account_id"] = row.get("account_id") or route["account_id"]
            row["account_name_snapshot"] = row.get("account_name_snapshot") or route["account_name"]
            row[method_field] = row.get(method_field) or route["method_id"]
            name_field = "preferred_payment_method_name_snapshot" if method_field == "preferred_payment_method_id" else "payment_method_name_snapshot"
            if name_field in fields:
                row[name_field] = row.get(name_field) or route["method_name"]
            if row != before:
                changed += 1
        if changed:
            report["support_rows_changed"][filename] = changed
        write_csv(data_dir / filename, fields, rows)


def migrate_internal_transfers(data_dir: Path, maps: Mapping[str, Any], report: dict[str, Any]) -> list[dict[str, Any]]:
    rows = read_csv(data_dir / "internal_transfers.csv", INTERNAL_TRANSFER_FIELDS)
    changed = 0
    for row in rows:
        before = dict(row)
        row["transfer_uid"] = row.get("transfer_uid") or f"transfer:{row.get('id') or uuid.uuid4().hex[:8]}"
        from_account = account_from_transfer_side(row.get("from_account") or row.get("from_account_id"), maps, default=MAIN_ACCOUNT)
        to_account = account_from_transfer_side(row.get("to_account") or row.get("to_account_id"), maps, default=MAIN_ACCOUNT)
        row["from_account_id"] = row.get("from_account_id") or from_account
        row["from_account_name_snapshot"] = row.get("from_account_name_snapshot") or account_name(maps, from_account)
        row["to_account_id"] = row.get("to_account_id") or to_account
        row["to_account_name_snapshot"] = row.get("to_account_name_snapshot") or account_name(maps, to_account)
        row["ledger_group_id"] = row.get("ledger_group_id") or f"lg_mig_{uuid.uuid5(uuid.NAMESPACE_URL, row['transfer_uid']).hex}"
        row["status"] = row.get("status") or "posted"
        row["transfer_kind"] = row.get("transfer_kind") or "account_transfer"
        row["created_at"] = row.get("created_at") or now()
        row["updated_at"] = row.get("updated_at") or now()
        if row != before:
            changed += 1
    if changed:
        report["internal_transfer_rows_changed"] = changed
    write_csv(data_dir / "internal_transfers.csv", INTERNAL_TRANSFER_FIELDS, rows)
    return rows


def account_from_transfer_side(value: Any, maps: Mapping[str, Any], default: str) -> str:
    c = clean(value)
    if not c:
        return default
    if c in maps["account_aliases"]:
        return maps["account_aliases"][c]
    if c in SPECIAL_ACCOUNT_METHODS:
        return SPECIAL_ACCOUNT_METHODS[c][0]
    return default


def rebuild_ledger(data_dir: Path, tx_index: Mapping[str, Any], transfer_rows: list[dict[str, Any]], maps: Mapping[str, Any], report: dict[str, Any]) -> None:
    ledger: list[dict[str, Any]] = []
    next_id = 1
    for uid, item in sorted(tx_index.items(), key=lambda kv: (str(kv[1]["row"].get("date") or ""), kv[0])):
        row = item["row"]
        route = item["route"]
        amount = money(row.get("amount"))
        if amount <= 0:
            continue
        if looks_like_credit_settlement(row):
            # two-sided settlement ledger, while CSV remains a historical expense row
            for account_id, signed, direction, kind, notes in [
                (MAIN_ACCOUNT, -amount, "out", "credit_statement_cash_out", "Credit-card statement payment from main bank."),
                (CREDIT_ACCOUNT, amount, "liability_decrease", "credit_liability_decrease", "Credit-card liability reduced by statement payment."),
            ]:
                ledger.append(make_ledger_row(next_id, row, route, account_id, account_name(maps, account_id), signed, direction, kind, notes, source_kind="legacy_migration_v2"))
                next_id += 1
        else:
            ledger.append(make_ledger_row(next_id, row, route, route["account_id"], route["account_name"], route["signed_amount"], route["direction"], route["movement_kind"], "Backfilled from legacy transaction row.", source_kind="legacy_migration_v2"))
            next_id += 1
    for tr in transfer_rows:
        amount = money(tr.get("amount"))
        if amount <= 0:
            continue
        group = tr.get("ledger_group_id") or f"lg_mig_{uuid.uuid4().hex}"
        meta = json.dumps({"transfer_uid": tr.get("transfer_uid"), "backfilled_by": "migrate_legacy_data_to_current_logic_v2"}, ensure_ascii=False, sort_keys=True)
        for account_id, signed, direction, kind, counterparty in [
            (tr.get("from_account_id") or MAIN_ACCOUNT, -amount, "out", "transfer_out", tr.get("to_account_id") or ""),
            (tr.get("to_account_id") or MAIN_ACCOUNT, amount, "in", "transfer_in", tr.get("from_account_id") or ""),
        ]:
            ledger.append({
                "id": str(next_id), "ledger_group_id": group, "transaction_uid": tr.get("transfer_uid", ""),
                "transaction_type": "transfer", "transaction_id": str(tr.get("id") or ""), "source_kind": "internal_transfer", "source_id": str(tr.get("id") or ""),
                "date": tr.get("date") or date.today().isoformat(), "effective_date": tr.get("date") or date.today().isoformat(),
                "account_id": account_id, "account_name_snapshot": account_name(maps, account_id),
                "counterparty_account_id": counterparty, "counterparty_account_name_snapshot": account_name(maps, counterparty) if counterparty else "",
                "payment_method_id": tr.get("fee_payment_method_id", ""), "payment_method_name_snapshot": tr.get("fee_payment_method_name_snapshot", ""),
                "movement_kind": kind, "direction": direction, "amount": fmt(amount), "currency": "EUR", "signed_amount": fmt(signed),
                "status": tr.get("status") or "posted", "is_void": "0", "voided_by_ledger_group_id": "", "created_from_resolution_json": meta,
                "notes": tr.get("description") or "Backfilled internal transfer.", "created_at": tr.get("created_at") or now(),
            })
            next_id += 1
    report["ledger_rows_rebuilt"] = len(ledger)
    write_csv(data_dir / "account_ledger.csv", ACCOUNT_LEDGER_FIELDS, ledger)


def make_ledger_row(next_id: int, row: Mapping[str, Any], route: Mapping[str, Any], account_id: str, account_label: str, signed: float, direction: str, movement_kind: str, notes: str, *, source_kind: str) -> dict[str, str]:
    amount = money(row.get("amount"))
    uid = str(row.get("transaction_uid") or "")
    return {
        "id": str(next_id), "ledger_group_id": str(row.get("ledger_group_id") or ""), "transaction_uid": uid,
        "transaction_type": uid.split(":", 1)[0] if ":" in uid else "", "transaction_id": str(row.get("id") or ""),
        "source_kind": source_kind, "source_id": str(row.get("id") or ""),
        "date": str(row.get("date") or "")[:10], "effective_date": str(row.get("date") or "")[:10],
        "account_id": account_id, "account_name_snapshot": account_label,
        "counterparty_account_id": "", "counterparty_account_name_snapshot": "",
        "payment_method_id": str(row.get("payment_method_id") or route.get("method_id") or ""),
        "payment_method_name_snapshot": str(row.get("payment_method_name_snapshot") or route.get("method_name") or ""),
        "movement_kind": movement_kind, "direction": direction, "amount": fmt(amount), "currency": "EUR", "signed_amount": fmt(signed),
        "status": "posted", "is_void": "0", "voided_by_ledger_group_id": "",
        "created_from_resolution_json": str(row.get("payment_resolution_json") or ""),
        "notes": notes, "created_at": str(row.get("created_at") or now()),
    }


def backfill_receipts(data_dir: Path, tx_index: Mapping[str, Any], report: dict[str, Any], *, mode: str) -> None:
    payload = read_json(data_dir / "receipts.json", {"schema_version": 1, "receipts": {}, "updated_at": ""})
    if not isinstance(payload, dict):
        payload = {"schema_version": 1, "receipts": {}, "updated_at": ""}
    receipts = payload.get("receipts") if isinstance(payload.get("receipts"), dict) else {}
    added = 0
    for uid, item in tx_index.items():
        if uid in receipts:
            continue
        row = item["row"]
        tx_type = item["type"]
        if mode == "none":
            continue
        # Expenses/investments get a paper-style item list. Incomes get a minimal receipt-like note.
        item_name = label(row.get("description")) or label(row.get("sub_category")) or label(row.get("category")) or "Item 001"
        amount = money(row.get("amount"))
        receipts[uid] = {
            "transaction_uid": uid,
            "merchant": label(row.get("description")) or label(row.get("category")) or "Receipt",
            "purchased_at": str(row.get("date") or "")[:10],
            "card_label": label(row.get("payment_method_name_snapshot") or row.get("payment_method")),
            "card_last4": "",
            "card_network": "",
            "account_label": label(row.get("account_name_snapshot")),
            "items": [{"name": item_name, "qty": 1.0, "unit_price": amount, "line_total": amount, "note": "Legacy transaction backfill"}],
            "discount_type": "none",
            "discount_value": 0.0,
            "notes": "Generated from a legacy transaction row. Edit this receipt to replace the default item with a real shopping list.",
            "updated_at": now(),
        }
        added += 1
    payload["schema_version"] = 1
    payload["receipts"] = receipts
    payload["updated_at"] = now()
    report["receipts_added"] = added
    write_json(data_dir / "receipts.json", payload)


def write_migration_info(data_dir: Path, report: Mapping[str, Any]) -> None:
    path = data_dir / "migration_info.json"
    payload = read_json(path, {"schema_version": 1})
    if not isinstance(payload, dict):
        payload = {"schema_version": 1}
    payload["legacy_data_backfill_v2"] = {
        "applied_at": now(),
        "tool": "migrate_legacy_data_to_current_logic_v2.py",
        "receipt_aware": True,
        "default_missing_bank_payment_method": MAIN_DEBIT,
        "report": dict(report),
    }
    # Do not set ledger authoritative: account_scope_service currently falls back to CSV math, and
    # _ledger_balance_for_account() is intentionally incomplete in repo(50). The rebuilt ledger is
    # useful for drawer/detail history, not as the source of truth yet.
    payload["ledger_migration"] = {"backfilled": True, "authoritative": False, "reason": "repo50 account_scope_service still uses CSV transaction math"}
    write_json(path, payload)


def backup_data_dir(data_dir: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = data_dir.parent / f"{data_dir.name}_backup_before_legacy_v2_{stamp}"
    shutil.copytree(data_dir, backup_root)
    return backup_root


def clear_cache_near(data_dir: Path, report: dict[str, Any]) -> None:
    candidates = [data_dir / "cache", data_dir.parent / "cache", data_dir.parent.parent / "cache"]
    cleared = []
    for path in candidates:
        if path.exists() and path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
            cleared.append(str(path))
    report["cache_dirs_cleared"] = cleared


def run(args: argparse.Namespace) -> dict[str, Any]:
    data_dir = find_data_dir(args.data_dir)
    report: dict[str, Any] = {
        "data_dir": str(data_dir),
        "dry_run": bool(args.dry_run),
        "accounts_added": [],
        "payment_methods_added": [],
        "payment_methods_repaired": [],
        "transaction_rows_changed": {},
        "pending_rows_changed": 0,
        "recurring_rows_changed": 0,
        "support_rows_changed": {},
        "internal_transfer_rows_changed": 0,
        "ledger_rows_rebuilt": 0,
        "receipts_added": 0,
        "cache_dirs_cleared": [],
    }

    work_dir = data_dir
    tmp_parent = None
    if args.dry_run:
        tmp_parent = data_dir.parent / f".{data_dir.name}_dry_run_{uuid.uuid4().hex[:8]}"
        shutil.copytree(data_dir, tmp_parent)
        work_dir = tmp_parent
    else:
        backup = backup_data_dir(data_dir)
        report["backup_dir"] = str(backup)

    accounts_payload, methods_payload = ensure_current_account_payment_config(work_dir, report)
    write_json(work_dir / "accounts.json", accounts_payload)
    write_json(work_dir / "payment_methods.json", methods_payload)
    maps = build_maps(accounts_payload, methods_payload)

    tx_index = migrate_transactions(work_dir, maps, report)
    migrate_pending_recurring(work_dir, maps, report)
    migrate_support_tables(work_dir, maps, report)
    transfer_rows = migrate_internal_transfers(work_dir, maps, report)
    rebuild_ledger(work_dir, tx_index, transfer_rows, maps, report)
    backfill_receipts(work_dir, tx_index, report, mode=args.receipts)
    write_migration_info(work_dir, report)
    if args.clear_cache:
        clear_cache_near(work_dir, report)

    if args.dry_run and tmp_parent:
        shutil.rmtree(tmp_parent, ignore_errors=True)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill legacy Money Manager data to the current payment/receipt model.")
    parser.add_argument("--data-dir", required=True, help="Flat user_data folder, or a user folder that contains user_data.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="Preview changes on a temporary copy.")
    group.add_argument("--apply", action="store_true", help="Apply changes to the selected data folder after creating a backup.")
    parser.add_argument("--receipts", choices=["missing-default", "none"], default="missing-default", help="Create default receipt records for transactions that have no receipt yet.")
    parser.add_argument("--clear-cache", action="store_true", default=True, help="Clear nearby cache folders after apply/dry-run copy.")
    args = parser.parse_args()
    report = run(args)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if args.dry_run:
        print("\nDRY RUN ONLY. No files in the original data folder were changed.")
    else:
        print("\nApplied. Restart Money Manager and hard-refresh the browser. If needed, restore from backup_dir above.")
    return 0


if __name__ == "__main__":
    # <user_id_dir> == MoneyManagerData\data\users\<user_id> [decrypted]
    # >> .venv\Scripts\python.exe tools\migrate_legacy_data_to_current_logic_v2.py --data-dir <user_id_dir> --dry-run
    # >> .venv\Scripts\python.exe tools\migrate_legacy_data_to_current_logic_v2.py --data-dir <user_id_dir> --apply
    raise SystemExit(main())
