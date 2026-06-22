from __future__ import annotations

import csv
from copy import deepcopy
from pathlib import Path
from typing import Any

from money_manager.config.user_defaults import USER_CONFIG_DEFAULTS, default_for
from money_manager.config.user_paths import get_user_data_dir
from money_manager.domain.constants import (
    DEBT_FIELDS,
    DEBT_RULE_FIELDS,
    EXPENSE_PROJECT_FIELDS,
    EXPENSE_PROJECT_MOVEMENT_FIELDS,
    EXPENSE_PROJECT_PLANNED_ITEM_FIELDS,
    INTERNAL_TRANSFER_FIELDS,
    INVESTMENT_ASSET_FIELDS,
    PARENT_SUPPORT_FIELDS,
    PARENT_SUPPORT_RULE_FIELDS,
    PAYABLE_FIELDS,
    PENDING_FIELDS,
    RECEIVABLE_FIELDS,
    RECURRING_FIELDS,
    SPARAGNAT_FIELDS,
    TRANSACTION_FIELDS,
)
from money_manager.security.protection_manager import read_json, write_json_atomic
from money_manager.services._user_config import deep_merge_defaults

CSV_SCHEMAS: dict[str, list[str]] = {
    "expenses.csv": TRANSACTION_FIELDS,
    "incomes.csv": TRANSACTION_FIELDS,
    "investments.csv": TRANSACTION_FIELDS,
    "investment_assets.csv": INVESTMENT_ASSET_FIELDS,
    "pending.csv": PENDING_FIELDS,
    "recurring.csv": RECURRING_FIELDS,
    "debts.csv": DEBT_FIELDS,
    "debt_rules.csv": DEBT_RULE_FIELDS,
    "payables.csv": PAYABLE_FIELDS,
    "receivables.csv": RECEIVABLE_FIELDS,
    "parent_support.csv": PARENT_SUPPORT_FIELDS,
    "parent_support_rules.csv": PARENT_SUPPORT_RULE_FIELDS,
    "expense_projects.csv": EXPENSE_PROJECT_FIELDS,
    "expense_project_movements.csv": EXPENSE_PROJECT_MOVEMENT_FIELDS,
    "expense_project_planned_items.csv": EXPENSE_PROJECT_PLANNED_ITEM_FIELDS,
    "internal_transfers.csv": INTERNAL_TRANSFER_FIELDS,
    "sparagnat_fottut.csv": SPARAGNAT_FIELDS,
}

JSON_DEFAULTS: dict[str, Any] = {
    "currencies.json": {},
    "notification_state.json": {"version": 1, "read": {}, "history": []},
    "investment_market_cache.json": {"symbols": {}, "last_refresh_attempt": ""},
}

DOCUMENT_METADATA_DEFAULT = {"schema_version": 1, "documents": []}


def ensure_user_schema(user_id: str | None = None) -> dict[str, Any]:
    """Repair the current user's files without destructive migrations.

    This helper is intentionally conservative: it creates missing expected files,
    adds missing CSV columns, and merges missing JSON schema/default keys.  It
    never deletes user data and never touches data/_system/users.json.
    """
    user_dir = get_user_data_dir(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "csv_created": [],
        "csv_columns_added": {},
        "json_repaired": [],
        "document_metadata_created": False,
    }

    for filename, fields in CSV_SCHEMAS.items():
        created, added = ensure_csv_schema(user_dir / filename, fields)
        if created:
            report["csv_created"].append(filename)
        if added:
            report["csv_columns_added"][filename] = added

    for filename, default_payload in JSON_DEFAULTS.items():
        if ensure_json_file(user_dir / filename, default_payload):
            report["json_repaired"].append(filename)

    for filename in USER_CONFIG_DEFAULTS:
        if ensure_user_config_schema(user_dir / filename, filename):
            report["json_repaired"].append(filename)

    documents_dir = user_dir / "documents"
    documents_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = documents_dir / "_metadata.json"
    if not metadata_path.exists():
        write_json_atomic(metadata_path, DOCUMENT_METADATA_DEFAULT)
        report["document_metadata_created"] = True
    else:
        if ensure_json_file(metadata_path, DOCUMENT_METADATA_DEFAULT):
            report["json_repaired"].append("documents/_metadata.json")

    for folder in ("Cedolini", "Tasse - Detrazioni Fiscali"):
        (documents_dir / folder).mkdir(parents=True, exist_ok=True)

    return report


def ensure_csv_schema(path: Path, fieldnames: list[str]) -> tuple[bool, list[str]]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.stat().st_size == 0:
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
        return True, []

    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        existing_fields = list(reader.fieldnames or [])
        rows = list(reader)

    if not existing_fields:
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
        return True, []

    missing = [field for field in fieldnames if field not in existing_fields]
    if not missing:
        return False, []

    final_fields = [field for field in fieldnames if field in existing_fields or field in missing]
    final_fields.extend(field for field in existing_fields if field not in final_fields)
    for row in rows:
        for field in missing:
            row[field] = ""

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=final_fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in final_fields})
    return False, missing


def ensure_json_file(path: Path, default_payload: Any) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = read_json(path, None)
    if raw is None:
        write_json_atomic(path, deepcopy(default_payload))
        return True
    repaired = deep_merge_defaults(default_payload, raw)
    if repaired != raw:
        write_json_atomic(path, repaired)
        return True
    return False


def ensure_user_config_schema(path: Path, filename: str) -> bool:
    default_payload = default_for(filename)
    raw = read_json(path, None)
    repaired = deep_merge_defaults(default_payload, raw)
    if not isinstance(repaired, dict):
        repaired = default_payload
    if not repaired.get("schema_version"):
        repaired["schema_version"] = default_payload.get("schema_version", 1)
    if raw != repaired or not path.exists():
        write_json_atomic(path, repaired)
        return True
    return False
