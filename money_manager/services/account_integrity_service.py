from __future__ import annotations
from io import StringIO

import csv
import uuid
from pathlib import Path
from typing import Any, Iterable, Mapping

from money_manager.config.user_defaults import USER_CONFIG_DEFAULTS
from money_manager.config.user_paths import get_user_data_dir
from money_manager.domain.constants import ACCOUNT_LEDGER_FIELDS, INTERNAL_TRANSFER_FIELDS, TRANSACTION_FIELDS
from money_manager.security.protection_manager import read_json
from money_manager.security.secure_storage import read_csv_secure, write_csv_secure
from money_manager.services.account_config_service import load_accounts_config
from money_manager.services.payment_method_service import all_payment_methods, ensure_payment_methods_file, validate_payment_method
from money_manager.services.profile_service import load_profile, migrate_profile_bank_info
from money_manager.services.schema_service import CSV_SCHEMAS, JSON_DEFAULTS, ensure_user_schema
from money_manager.security.secure_storage import read_binary_secure

TRANSACTION_FILES = ["expenses.csv", "incomes.csv", "investments.csv"]
REFERENCE_CSV_FILES = ["pending.csv", "recurring.csv", "credit_settlements.csv", "internal_transfers.csv"]


def full_integrity_report(user_id: str | None = None) -> dict[str, Any]:
    report = _empty_report()
    for validator in [
        validate_accounts,
        validate_payment_methods,
        validate_transaction_snapshots,
        validate_ledger_consistency,
        validate_credit_settlements,
        validate_internal_transfers,
        validate_profile_defaults,
        validate_recurring_and_pending_references,
        validate_scoped_account_model,
        validate_backup_schema_files,
    ]:
        _merge(report, validator(user_id=user_id))
    report["ok"] = not report["errors"]
    return report


def validate_accounts(user_id: str | None = None) -> dict[str, Any]:
    report = _empty_report()
    accounts_payload = load_accounts_config(user_id=user_id)
    accounts = [account for account in accounts_payload.get("accounts", []) if isinstance(account, Mapping)]
    ids = [_account_id(account) for account in accounts]
    report["counts"]["accounts"] = len(accounts)
    seen: set[str] = set()
    for account in accounts:
        account_id = _account_id(account)
        label = account.get("label") or account.get("name") or account_id
        if not account_id:
            report["errors"].append("Account with missing id/key found in accounts.json.")
            continue
        if account_id in seen:
            report["errors"].append(f"Duplicate account id/key: {account_id}.")
        seen.add(account_id)
        parent = str(account.get("parent_account_id") or account.get("parent_key") or "").strip()
        if parent and parent not in ids:
            report["errors"].append(f"Account {label} points to missing parent account {parent}.")
        if parent == account_id:
            report["errors"].append(f"Account {label} cannot be its own parent.")
        if account.get("is_current_account") and account.get("is_container"):
            report["warnings"].append(f"Account {label} is both current account and container; review account type.")
        if account.get("iban") and not account.get("institution"):
            report["warnings"].append(f"Account {label} has an IBAN but no bank/institution name.")
    return report


def validate_payment_methods(user_id: str | None = None) -> dict[str, Any]:
    report = _empty_report()
    accounts_payload = load_accounts_config(user_id=user_id)
    accounts = accounts_payload.get("accounts", [])
    active_accounts = {_account_id(a) for a in accounts if isinstance(a, Mapping) and a.get("is_active", True) and not a.get("is_closed")}
    archived_accounts = {_account_id(a) for a in accounts if isinstance(a, Mapping) and (not a.get("is_active", True) or a.get("is_closed"))}
    methods = all_payment_methods(include_archived=True, user_id=user_id)
    report["counts"]["payment_methods"] = len(methods)
    method_ids = {str(method.get("id") or "") for method in methods}
    for method in methods:
        method_id = str(method.get("id") or "")
        label = str(method.get("name") or method_id or "<unnamed>")
        errors = validate_payment_method(method, accounts_payload, methods)
        for err in errors:
            if err.startswith("missing_") and method.get("settlement_mode") == "delayed":
                report["errors"].append(f"Payment method {label}: {err.replace('_', ' ')}.")
            elif "unknown" in err or "cycle" in err:
                report["errors"].append(f"Payment method {label}: {err.replace('_', ' ')}.")
            else:
                report["warnings"].append(f"Payment method {label}: {err.replace('_', ' ')}.")
        if not method.get("is_archived") and method.get("is_active", True):
            for field in ["linked_account_id", "funding_account_id", "settlement_account_id", "liability_account_id"]:
                value = str(method.get(field) or "").strip()
                if value in archived_accounts:
                    report["warnings"].append(f"Payment method {label} uses archived/closed account {value} in {field}.")
        if method.get("settlement_mode") == "delegated":
            delegate = str(method.get("delegates_to_payment_method_id") or "").strip()
            if delegate and delegate not in method_ids:
                report["errors"].append(f"Payment method {label} delegates to missing payment method {delegate}.")
        if method.get("method_type") == "credit_card" or method.get("settlement_mode") == "delayed":
            if not method.get("liability_account_id"):
                report["errors"].append(f"Credit card payment method {label} has no liability account.")
            if not method.get("settlement_account_id"):
                report["errors"].append(f"Credit card payment method {label} has no settlement account.")
    return report


def validate_transaction_snapshots(user_id: str | None = None) -> dict[str, Any]:
    report = _empty_report()
    user_dir = get_user_data_dir(user_id)
    account_ids, method_ids = _known_ids(user_id=user_id)
    missing_method = 0
    for filename in TRANSACTION_FILES + ["sparagnat_fottut.csv"]:
        path = user_dir / filename
        rows, headers = _read_csv(path)
        if not rows:
            continue
        for row_num, row in enumerate(rows, start=2):
            if not str(row.get("transaction_uid") or "").strip():
                report["warnings"].append(f"{filename}:{row_num} is missing transaction_uid.")
            account_id = str(row.get("account_id") or row.get("account_key_snapshot") or "").strip()
            if account_id and account_id not in account_ids:
                report["errors"].append(f"{filename}:{row_num} points to missing account {account_id}.")
            method_id = str(row.get("payment_method_id") or "").strip()
            if not method_id:
                missing_method += 1
            elif method_id not in method_ids:
                report["errors"].append(f"{filename}:{row_num} points to missing payment method {method_id}.")
            if method_id and not str(row.get("payment_method_name_snapshot") or "").strip():
                report["warnings"].append(f"{filename}:{row_num} has payment_method_id without name snapshot.")
            if account_id and not str(row.get("account_name_snapshot") or "").strip():
                report["warnings"].append(f"{filename}:{row_num} has account_id without account name snapshot.")
    report["counts"]["transactions_without_payment_method_id"] = missing_method
    return report


def validate_ledger_consistency(user_id: str | None = None) -> dict[str, Any]:
    report = _empty_report()
    user_dir = get_user_data_dir(user_id)
    path = user_dir / "account_ledger.csv"
    rows, headers = _read_csv(path)
    report["counts"]["ledger_rows"] = len(rows)
    missing_columns = [field for field in ACCOUNT_LEDGER_FIELDS if field not in headers]
    if missing_columns:
        report["errors"].append(f"account_ledger.csv is missing columns: {', '.join(missing_columns)}.")
    account_ids, method_ids = _known_ids(user_id=user_id)
    for row_num, row in enumerate(rows, start=2):
        account_id = str(row.get("account_id") or "").strip()
        if account_id and account_id not in account_ids:
            report["errors"].append(f"account_ledger.csv:{row_num} points to missing account {account_id}.")
        method_id = str(row.get("payment_method_id") or "").strip()
        if method_id and method_id not in method_ids:
            report["errors"].append(f"account_ledger.csv:{row_num} points to missing payment method {method_id}.")
        _check_number(report, row.get("amount"), f"account_ledger.csv:{row_num} amount")
        _check_number(report, row.get("signed_amount"), f"account_ledger.csv:{row_num} signed_amount")
        if row.get("status") not in {"", "posted", "scheduled", "voided", "draft"}:
            report["warnings"].append(f"account_ledger.csv:{row_num} has unusual ledger status {row.get('status')}.")
    return report


def validate_credit_settlements(user_id: str | None = None) -> dict[str, Any]:
    report = _empty_report()
    user_dir = get_user_data_dir(user_id)
    rows, _ = _read_csv(user_dir / "credit_settlements.csv")
    account_ids, method_ids = _known_ids(user_id=user_id)
    for row_num, row in enumerate(rows, start=2):
        method_id = str(row.get("payment_method_id") or "").strip()
        liability_id = str(row.get("liability_account_id") or "").strip()
        settlement_id = str(row.get("settlement_account_id") or "").strip()
        if method_id and method_id not in method_ids:
            report["errors"].append(f"credit_settlements.csv:{row_num} uses missing payment method {method_id}.")
        if liability_id and liability_id not in account_ids:
            report["errors"].append(f"credit_settlements.csv:{row_num} uses missing liability account {liability_id}.")
        if settlement_id and settlement_id not in account_ids:
            report["errors"].append(f"credit_settlements.csv:{row_num} uses missing settlement account {settlement_id}.")
    return report


def validate_internal_transfers(user_id: str | None = None) -> dict[str, Any]:
    report = _empty_report()
    user_dir = get_user_data_dir(user_id)
    rows, headers = _read_csv(user_dir / "internal_transfers.csv")
    account_ids, method_ids = _known_ids(user_id=user_id)
    missing_columns = [field for field in INTERNAL_TRANSFER_FIELDS if field not in headers]
    if missing_columns:
        report["errors"].append(f"internal_transfers.csv is missing columns: {', '.join(missing_columns)}.")
    for row_num, row in enumerate(rows, start=2):
        for field in ["from_account_id", "to_account_id"]:
            value = str(row.get(field) or "").strip()
            if value and value not in account_ids:
                report["errors"].append(f"internal_transfers.csv:{row_num} uses missing {field} {value}.")
        fee_method = str(row.get("fee_payment_method_id") or "").strip()
        if fee_method and fee_method not in method_ids:
            report["errors"].append(f"internal_transfers.csv:{row_num} uses missing fee payment method {fee_method}.")
    return report


def validate_profile_defaults(user_id: str | None = None) -> dict[str, Any]:
    report = _empty_report()
    profile = load_profile(user_id=user_id)
    accounts_payload = load_accounts_config(user_id=user_id)
    accounts = [_account_id(a) for a in accounts_payload.get("accounts", []) if isinstance(a, Mapping)]
    active_accounts = {
        _account_id(a) for a in accounts_payload.get("accounts", [])
        if isinstance(a, Mapping) and a.get("is_active", True) and not a.get("is_closed")
    }
    methods = {str(method.get("id") or ""): method for method in all_payment_methods(include_archived=True, user_id=user_id)}
    default_account = str(profile.get("default_current_account_id") or profile.get("default_main_account") or "").strip()
    if default_account and default_account not in accounts:
        report["errors"].append(f"Profile default current account is missing: {default_account}.")
    elif default_account and default_account not in active_accounts:
        report["warnings"].append(f"Profile default current account is archived or closed: {default_account}.")
    elif not default_account:
        report["warnings"].append("Profile has no default_current_account_id.")
    default_method = str(profile.get("default_payment_method_id") or "").strip()
    if default_method:
        method = methods.get(default_method)
        if not method:
            report["errors"].append(f"Profile default payment method is missing: {default_method}.")
        elif method.get("is_archived") or not method.get("is_active", True):
            report["warnings"].append(f"Profile default payment method is archived: {default_method}.")
    migration = migrate_profile_bank_info(profile, user_id=user_id)
    if not migration.get("ok"):
        report["warnings"].append(f"Profile bank fields were not migrated: {migration.get('reason')}.")
    if any(profile.get(field) for field in ["bank_name", "iban", "bic_swift"]):
        report["info"].append("Deprecated profile bank fields still exist for compatibility; bank ownership is stored on accounts.json.")
    return report


def validate_recurring_and_pending_references(user_id: str | None = None) -> dict[str, Any]:
    report = _empty_report()
    user_dir = get_user_data_dir(user_id)
    account_ids, method_ids = _known_ids(user_id=user_id)
    archived_methods = {
        str(method.get("id") or "") for method in all_payment_methods(include_archived=True, user_id=user_id)
        if method.get("is_archived") or not method.get("is_active", True)
    }
    for filename in ["pending.csv", "recurring.csv"]:
        rows, _ = _read_csv(user_dir / filename)
        for row_num, row in enumerate(rows, start=2):
            account_id = str(row.get("account_id") or "").strip()
            method_id = str(row.get("payment_method_id") or "").strip()
            if account_id and account_id not in account_ids:
                report["errors"].append(f"{filename}:{row_num} uses missing account {account_id}.")
            if method_id and method_id not in method_ids:
                report["errors"].append(f"{filename}:{row_num} uses missing payment method {method_id}.")
            elif method_id in archived_methods:
                report["warnings"].append(f"{filename}:{row_num} uses archived payment method {method_id}.")
    return report


def validate_scoped_account_model(user_id: str | None = None) -> dict[str, Any]:
    """Validate the multi-financial-center scope model without mutating data."""
    report = _empty_report()
    section = {
        "financial_centers": [],
        "dependent_accounts": [],
        "payment_methods": [],
        "errors": [],
        "warnings": [],
    }
    try:
        from money_manager.services.account_scope_service import (
            all_financial_center_summaries,
            dependent_accounts_for,
            financial_centers,
            global_balance_summary,
            payment_methods_for_account,
            resolve_account_scope,
            scope_balance_summary,
        )
    except Exception as exc:
        msg = f"Scoped account model could not be imported: {exc}."
        report["errors"].append(msg)
        section["errors"].append(msg)
        report["scoped_account_model"] = section
        return report

    payload = load_accounts_config(user_id=user_id)
    accounts = [a for a in payload.get("accounts", []) if isinstance(a, Mapping)]
    account_ids = {_account_id(a) for a in accounts if _account_id(a)}
    centers = []
    dependents = []

    for account in accounts:
        account_id = _account_id(account)
        label = str(account.get("label") or account.get("name") or account_id or "<unnamed>")
        is_center = bool(account.get("is_financial_center"))
        is_dependent = bool(account.get("is_dependent_account") or account.get("parent_account_id") or account.get("parent_key"))
        if account.get("is_current_account") and not is_center:
            section["errors"].append(f"Current account {label} is not marked as a financial center.")
        if is_center and is_dependent and account.get("liquidity_rollup_policy") != "standalone":
            section["errors"].append(f"Financial center {label} is also dependent without standalone rollup policy.")
        parent = str(account.get("parent_account_id") or account.get("parent_key") or "").strip()
        if is_dependent:
            dependents.append(account_id)
            if not parent:
                section["warnings"].append(f"Dependent account {label} has no parent_account_id.")
            elif parent not in account_ids:
                section["errors"].append(f"Dependent account {label} points to invalid parent {parent}.")
        if is_center:
            centers.append(account_id)

    # Simple parent cycle check.
    parents = {_account_id(a): str(a.get("parent_account_id") or a.get("parent_key") or "").strip() for a in accounts}
    for account_id in account_ids:
        seen: set[str] = set()
        cur = account_id
        while cur:
            if cur in seen:
                section["errors"].append(f"Account parent cycle detected at {account_id}.")
                break
            seen.add(cur)
            cur = parents.get(cur, "")

    try:
        section["financial_centers"] = [
            {
                "account_id": item.get("account_id"),
                "label": item.get("label"),
                "net_balance": item.get("net_balance"),
                "projected_net": item.get("projected_net"),
            }
            for item in all_financial_center_summaries(user_id=user_id)
        ]
        section["dependent_accounts"] = dependents
        section["payment_methods"] = [
            {"id": str(m.get("id") or ""), "name": str(m.get("name") or "")}
            for m in all_payment_methods(include_archived=False, user_id=user_id)
        ]
        global_summary = global_balance_summary(user_id=user_id)
        # All Conti intentionally includes active dependent/prepaid balances in
        # addition to top-level financial centers.  A difference from the center
        # cards is therefore expected and is no longer an integrity warning.
        section["global_net_balance"] = float(global_summary.get("net_balance", 0.0) or 0.0)
        resolve_account_scope("global", user_id=user_id)
        for center in financial_centers(user_id=user_id, include_archived=True):
            center_id = _account_id(center)
            scope_balance_summary(f"account:{center_id}", user_id=user_id)
            dependent_accounts_for(center_id, user_id=user_id, include_archived=True)
            payment_methods_for_account(center_id, user_id=user_id, include_archived=True)
    except Exception as exc:
        section["errors"].append(f"Scoped balance validation failed: {exc}.")

    report["errors"].extend(section["errors"])
    report["warnings"].extend(section["warnings"])
    report["counts"]["financial_centers"] = len(centers)
    report["counts"]["dependent_accounts"] = len(dependents)
    report["scoped_account_model"] = section
    return report


def validate_backup_schema_files(user_id: str | None = None) -> dict[str, Any]:
    report = _empty_report()
    user_dir = get_user_data_dir(user_id)
    for filename, fields in CSV_SCHEMAS.items():
        path = user_dir / filename
        if not path.exists():
            report["warnings"].append(f"Missing CSV file: {filename}.")
            continue
        _, headers = _read_csv(path)
        missing = [field for field in fields if field not in headers]
        if missing:
            report["warnings"].append(f"{filename} is missing schema columns: {', '.join(missing)}.")
    for filename in set(USER_CONFIG_DEFAULTS) | set(JSON_DEFAULTS) | {"account_events.json", "payment_methods.json"}:
        if not (user_dir / filename).exists():
            report["warnings"].append(f"Missing JSON file: {filename}.")
    return report


def rebuild_ledger_preview(user_id: str | None = None) -> dict[str, Any]:
    user_dir = get_user_data_dir(user_id)
    ledger_rows, _ = _read_csv(user_dir / "account_ledger.csv")
    ledger_transaction_uids = {str(row.get("transaction_uid") or "").strip() for row in ledger_rows if row.get("transaction_uid")}
    transaction_rows = 0
    missing_ledger = 0
    with_ledger = 0
    without_uid = 0
    for filename in TRANSACTION_FILES:
        rows, _ = _read_csv(user_dir / filename)
        for row in rows:
            transaction_rows += 1
            uid = str(row.get("transaction_uid") or "").strip()
            if not uid:
                without_uid += 1
                continue
            if uid in ledger_transaction_uids or str(row.get("ledger_group_id") or "").strip():
                with_ledger += 1
            else:
                missing_ledger += 1
    return {
        "transaction_rows": transaction_rows,
        "ledger_rows": len(ledger_rows),
        "transactions_with_ledger": with_ledger,
        "transactions_missing_ledger": missing_ledger,
        "transactions_without_uid": without_uid,
        "destructive": False,
        "message": "Preview only. No historical ledger rows were changed.",
    }


def repair_safe(user_id: str | None = None, *, confirm: bool = False) -> dict[str, Any]:
    if not confirm:
        return {"ok": False, "error": "Confirmation required.", "changes": []}
    changes: list[str] = []
    schema_report = ensure_user_schema(user_id=user_id)
    for filename in schema_report.get("csv_created", []):
        changes.append(f"Created missing CSV file {filename}.")
    for filename, fields in schema_report.get("csv_columns_added", {}).items():
        changes.append(f"Added missing CSV columns to {filename}: {', '.join(fields)}.")
    for filename in schema_report.get("json_repaired", []):
        changes.append(f"Created/repaired JSON file {filename}.")

    ensure_payment_methods_file(user_id=user_id)
    changes.extend(_repair_transaction_snapshots(user_id=user_id))
    migrate_profile_bank_info(user_id=user_id)
    return {"ok": True, "changes": changes, "report": full_integrity_report(user_id=user_id)}


def _repair_transaction_snapshots(user_id: str | None = None) -> list[str]:
    user_dir = get_user_data_dir(user_id)
    accounts_payload = load_accounts_config(user_id=user_id)
    accounts_by_id = {_account_id(account): account for account in accounts_payload.get("accounts", []) if isinstance(account, Mapping)}
    methods_by_id = {str(method.get("id") or ""): method for method in all_payment_methods(include_archived=True, user_id=user_id)}
    changes: list[str] = []
    for filename in TRANSACTION_FILES + ["sparagnat_fottut.csv"]:
        path = user_dir / filename
        rows, headers = _read_csv(path)
        if not rows:
            continue
        final_headers = list(dict.fromkeys((headers or []) + TRANSACTION_FIELDS))
        changed_rows = 0
        for row in rows:
            if "transaction_uid" in final_headers and not str(row.get("transaction_uid") or "").strip():
                row["transaction_uid"] = f"tx_{uuid.uuid4().hex}"
                changed_rows += 1
            account_id = str(row.get("account_id") or row.get("account_key_snapshot") or "").strip()
            if account_id in accounts_by_id and not str(row.get("account_name_snapshot") or "").strip():
                account = accounts_by_id[account_id]
                row["account_name_snapshot"] = str(account.get("label") or account.get("name") or account_id)
                changed_rows += 1
            method_id = str(row.get("payment_method_id") or "").strip()
            if method_id in methods_by_id and not str(row.get("payment_method_name_snapshot") or "").strip():
                row["payment_method_name_snapshot"] = str(methods_by_id[method_id].get("name") or method_id)
                changed_rows += 1
        if changed_rows:
            _write_csv(path, final_headers, rows)
            changes.append(f"Filled safe transaction identifiers/snapshots in {filename}: {changed_rows} cells/rows updated.")
    return changes


def _known_ids(user_id: str | None = None) -> tuple[set[str], set[str]]:
    accounts_payload = load_accounts_config(user_id=user_id)
    account_ids = {_account_id(account) for account in accounts_payload.get("accounts", []) if isinstance(account, Mapping)}
    methods = all_payment_methods(include_archived=True, user_id=user_id)
    method_ids = {str(method.get("id") or "") for method in methods if method.get("id")}
    return account_ids, method_ids


def _empty_report() -> dict[str, Any]:
    return {
        "ok": True,
        "errors": [],
        "warnings": [],
        "info": [],
        "counts": {
            "accounts": 0,
            "payment_methods": 0,
            "ledger_rows": 0,
            "transactions_without_payment_method_id": 0,
        },
    }


def _merge(base: dict[str, Any], incoming: Mapping[str, Any]) -> None:
    base["errors"].extend(incoming.get("errors", []))
    base["warnings"].extend(incoming.get("warnings", []))
    base["info"].extend(incoming.get("info", []))
    for key, value in incoming.get("counts", {}).items():
        if value:
            base["counts"][key] = value
    for key, value in incoming.items():
        if key not in {"ok", "errors", "warnings", "info", "counts"}:
            base[key] = value


def _read_csv(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    if not path.exists() or path.stat().st_size == 0:
        return [], []

    try:
        raw = read_binary_secure(path)
        text = raw.decode("utf-8-sig") if raw else ""
        if not text.strip():
            return [], []

        reader = csv.DictReader(StringIO(text))
        headers = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
        return rows, headers
    except Exception:
        return [], []


def _write_csv(path: Path, headers: list[str], rows: Iterable[Mapping[str, Any]]) -> None:
    write_csv_secure(path, headers, [dict(row) for row in rows])


def _account_id(account: Mapping[str, Any]) -> str:
    return str(account.get("key") or account.get("id") or "").strip()


def _check_number(report: dict[str, Any], value: Any, label: str) -> None:
    if value in {None, ""}:
        return
    try:
        float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        report["errors"].append(f"{label} is not numeric: {value}.")
