from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from typing import Any

from money_manager.config.user_defaults import USER_CONFIG_DEFAULTS, default_for
from money_manager.config.user_paths import get_user_data_dir
from money_manager.security.protection_manager import read_json, write_json_atomic
from money_manager.services._user_config import deep_merge_defaults
from money_manager.storage.data_file_service import ensure_csv_schema as _registry_ensure_csv_schema
from money_manager.storage.data_file_service import ensure_json_file as _registry_ensure_json_file
from money_manager.storage.data_file_service import ensure_user_files
from money_manager.storage.data_registry import csv_schemas, json_defaults

# Compatibility exports.  The registry is now the source of truth; these names
# remain available for old imports/tests.
CSV_SCHEMAS: dict[str, list[str]] = csv_schemas()
JSON_DEFAULTS: dict[str, Any] = json_defaults()
DOCUMENT_METADATA_DEFAULT = {"schema_version": 1, "documents": []}


def ensure_user_schema(user_id: str | None = None) -> dict[str, Any]:
    """Create/repair a user's data files through the central data registry.

    CSV repair preserves rows and unknown columns. JSON repair merges missing
    keys and never deletes user values. Account/payment files still pass through
    their dedicated normalization services because they contain richer routing
    logic than a static default merge can express.
    """
    user_dir = get_user_data_dir(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    report = ensure_user_files(str(user_dir.name))
    report.setdefault("document_metadata_created", False)

    account_payment_report = ensure_account_payment_model_schema(user_id)
    if account_payment_report.get("accounts_repaired"):
        report.setdefault("json_repaired", []).append("accounts.json")
    if account_payment_report.get("payment_methods_repaired"):
        report.setdefault("json_repaired", []).append("payment_methods.json")

    for folder in ("Cedolini", "Tasse - Detrazioni Fiscali"):
        (user_dir / "documents" / folder).mkdir(parents=True, exist_ok=True)

    return report


def ensure_account_payment_model_schema(user_id: str | None = None) -> dict[str, Any]:
    """Upgrade accounts.json to schema v3 and create/repair payment_methods.json."""
    if os.environ.get("MONEY_MANAGER_REPAIR_CONFIG_ON_READ", "0").strip() != "1":
        return {
            "accounts_repaired": False,
            "payment_methods_repaired": False,
            "from_accounts_schema": None,
            "payment_methods_created": False,
        }
    
    user_dir = get_user_data_dir(user_id)
    accounts_path = user_dir / "accounts.json"
    methods_path = user_dir / "payment_methods.json"
    raw_accounts = read_json(accounts_path, None)
    from_schema = raw_accounts.get("schema_version") if isinstance(raw_accounts, dict) else None
    methods_missing = not methods_path.exists()

    from money_manager.services.account_config_service import ensure_accounts_config
    from money_manager.services.payment_method_service import (
        ensure_payment_methods_file,
        write_account_payment_migration_report,
    )

    before_accounts = deepcopy(raw_accounts)
    accounts_payload = ensure_accounts_config(user_id=user_id)
    raw_methods = read_json(methods_path, None)
    before_methods = deepcopy(raw_methods)
    methods_payload = ensure_payment_methods_file(user_id=user_id)

    accounts_repaired = before_accounts != accounts_payload or from_schema != 3
    payment_methods_repaired = before_methods != methods_payload or methods_missing
    if raw_accounts is not None and (from_schema != 3 or methods_missing or accounts_repaired or payment_methods_repaired):
        notes: list[str] = []
        if from_schema != 3:
            notes.append("accounts.json upgraded to schema_version 3")
        if methods_missing:
            notes.append("payment_methods.json inferred from existing accounts.json")
        if accounts_repaired:
            notes.append("accounts.json normalized with financial-center, dependency, and liquidity-rollup fields")
        if payment_methods_repaired:
            notes.append("payment_methods.json normalized with account routing links")
        write_account_payment_migration_report(
            user_id,
            from_accounts_schema=from_schema,
            payment_methods_created=methods_missing,
            notes=notes,
        )
    return {
        "accounts_repaired": accounts_repaired,
        "payment_methods_repaired": payment_methods_repaired,
        "from_accounts_schema": from_schema,
        "payment_methods_created": methods_missing,
    }


def ensure_csv_schema(path: Path, fieldnames: list[str]) -> tuple[bool, list[str]]:
    return _registry_ensure_csv_schema(path, fieldnames, preserve_unknown_columns=True)


def ensure_json_file(path: Path, default_payload: Any) -> bool:
    return _registry_ensure_json_file(path, default_payload)


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
