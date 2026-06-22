from __future__ import annotations

import csv
import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from money_manager.config.user_paths import DATA_DIR, PROJECT_ROOT, SYSTEM_DIR, USERS_DIR, normalize_user_id
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
from money_manager.security.protection_manager import hash_password, read_json, verify_password, write_json_atomic

USERS_JSON = SYSTEM_DIR / "users.json"
SCHEMA_VERSION = 1

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
    "accounts.json": {"accounts": []},
    "currencies.json": {},
    "notification_state.json": {"version": 1, "read": {}, "history": []},
    "investment_market_cache.json": {"symbols": {}, "last_refresh_attempt": ""},
}

FLAT_DATA_FILENAMES = [*CSV_SCHEMAS.keys(), *JSON_DEFAULTS.keys()]
DOCUMENT_METADATA = {"schema_version": 1, "documents": []}


def _empty_payload() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "users": []}


def load_users() -> list[dict[str, Any]]:
    payload = read_json(USERS_JSON, _empty_payload())
    if not isinstance(payload, dict):
        return []
    users = payload.get("users", [])
    if not isinstance(users, list):
        return []
    clean: list[dict[str, Any]] = []
    for user in users:
        if isinstance(user, dict) and user.get("id") and user.get("username"):
            clean.append(user)
    return clean


def save_users(users: list[dict[str, Any]]) -> None:
    SYSTEM_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": SCHEMA_VERSION, "users": users}
    write_json_atomic(USERS_JSON, payload)


def has_any_user() -> bool:
    return bool(load_users())


def get_user_by_id(user_id: str | None) -> dict[str, Any] | None:
    wanted = normalize_user_id(user_id)
    for user in load_users():
        if normalize_user_id(user.get("id")) == wanted:
            return user
    return None


def get_user_by_username(username: str | None) -> dict[str, Any] | None:
    wanted = _normalize_username(username)
    if not wanted:
        return None
    for user in load_users():
        if _normalize_username(user.get("username")) == wanted:
            return user
    return None


def create_user(username: str, password: str, display_name: str | None = None, first_name: str | None = None, last_name: str | None = None) -> dict[str, Any]:
    username_clean = str(username or "").strip()
    if not username_clean:
        raise ValueError("Username is required.")
    if not str(password or ""):
        raise ValueError("Password is required.")
    if get_user_by_username(username_clean):
        raise ValueError("This username already exists.")

    users = load_users()
    first_user = len(users) == 0
    user_id = _unique_user_id(username_clean, users)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    first_name = str(first_name or "").strip()
    last_name = str(last_name or "").strip()
    display = str(display_name or "").strip() or " ".join(part for part in [first_name, last_name] if part).strip() or username_clean

    user = {
        "id": user_id,
        "username": username_clean,
        "username_normalized": _normalize_username(username_clean),
        "display_name": display,
        "first_name": first_name,
        "last_name": last_name,
        "password_hash": hash_password(password),
        "created_at": now,
        "active": True,
        "role": "owner" if first_user else "user",
    }

    ensure_user_data_folder(user_id, create_files=False)
    if first_user:
        migrate_flat_data_to_user(user_id)
    ensure_user_data_folder(user_id, create_files=True)
    _ensure_user_config_files(user_id, user)

    users.append(user)
    save_users(users)
    return user


def authenticate_user(username: str, password: str) -> dict[str, Any] | None:
    user = get_user_by_username(username)
    if not user or user.get("active") is False:
        return None
    if not verify_password(password, str(user.get("password_hash") or "")):
        return None
    ensure_user_data_folder(str(user.get("id")), create_files=True)
    return user


def ensure_user_data_folder(user_id: str, create_files: bool = True) -> Path:
    safe_id = normalize_user_id(user_id)
    user_dir = USERS_DIR / safe_id
    user_dir.mkdir(parents=True, exist_ok=True)
    for dirname in ("cache", "plots", "documents"):
        (user_dir / dirname).mkdir(parents=True, exist_ok=True)
    for folder in ("Cedolini", "Tasse - Detrazioni Fiscali"):
        (user_dir / "documents" / folder).mkdir(parents=True, exist_ok=True)
    metadata = user_dir / "documents" / "_metadata.json"
    if not metadata.exists():
        write_json_atomic(metadata, DOCUMENT_METADATA)
    if create_files:
        _ensure_default_data_files(user_dir)
        _ensure_user_config_files(safe_id, get_user_by_id(safe_id))
    return user_dir


def migrate_flat_data_to_user(user_id: str) -> dict[str, Any]:
    safe_id = normalize_user_id(user_id)
    user_dir = ensure_user_data_folder(safe_id, create_files=False)
    copied: list[str] = []
    skipped: list[str] = []

    for filename in FLAT_DATA_FILENAMES:
        source = DATA_DIR / filename
        target = user_dir / filename
        if source.exists() and source.is_file():
            if target.exists():
                skipped.append(filename)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied.append(filename)

    source_cache = DATA_DIR / "cache"
    target_cache = user_dir / "cache"
    if source_cache.exists() and source_cache.is_dir():
        for source in source_cache.rglob("*"):
            if not source.is_file():
                continue
            relative = source.relative_to(source_cache)
            target = target_cache / relative
            if target.exists():
                skipped.append(f"cache/{relative.as_posix()}")
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied.append(f"cache/{relative.as_posix()}")

    source_plots = PROJECT_ROOT / "static" / "plots"
    target_plots = user_dir / "plots"
    if source_plots.exists() and source_plots.is_dir():
        for source in source_plots.rglob("*"):
            if not source.is_file():
                continue
            relative = source.relative_to(source_plots)
            target = target_plots / relative
            if target.exists():
                skipped.append(f"plots/{relative.as_posix()}")
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied.append(f"plots/{relative.as_posix()}")

    for documents_name in ("documents", "Documents"):
        source_documents = PROJECT_ROOT / documents_name
        if not source_documents.exists() or not source_documents.is_dir():
            continue
        target_documents = user_dir / "documents"
        for source in source_documents.rglob("*"):
            if not source.is_file():
                continue
            relative = source.relative_to(source_documents)
            target = target_documents / relative
            if target.exists():
                skipped.append(f"documents/{relative.as_posix()}")
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied.append(f"documents/{relative.as_posix()}")

    marker = {
        "schema_version": 1,
        "migrated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "flat data folder",
        "copied": copied,
        "skipped_existing": skipped,
        "old_files_deleted": False,
    }
    write_json_atomic(user_dir / "migration_info.json", marker)
    return marker


def _ensure_default_data_files(user_dir: Path) -> None:
    for filename, headers in CSV_SCHEMAS.items():
        path = user_dir / filename
        if path.exists() and path.stat().st_size > 0:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=headers)
            writer.writeheader()

    for filename, default_payload in JSON_DEFAULTS.items():
        path = user_dir / filename
        if path.exists():
            continue
        write_json_atomic(path, default_payload)


def _ensure_user_config_files(user_id: str, user_hint: dict[str, Any] | None = None) -> None:
    """Create or repair per-user backend config JSON files.

    Imports are local to keep user creation independent from web/request startup and
    to avoid service import cycles. Every call is scoped to the normalized user_id.
    """
    from money_manager.services.contact_service import ensure_contacts_config
    from money_manager.services.custom_category_service import ensure_categories_config
    from money_manager.services.document_type_service import ensure_document_types_config
    from money_manager.services.navigation_service import ensure_navigation_config
    from money_manager.services.preferences_service import ensure_preferences_config
    from money_manager.services.profile_service import ensure_profile_config

    ensure_profile_config(user_id=user_id, user_hint=user_hint)
    ensure_preferences_config(user_id=user_id)
    ensure_categories_config(user_id=user_id)
    ensure_contacts_config(user_id=user_id)
    ensure_navigation_config(user_id=user_id)
    ensure_document_types_config(user_id=user_id)


def _normalize_username(username: str | None) -> str:
    return " ".join(str(username or "").strip().casefold().split())


def _unique_user_id(username: str, users: list[dict[str, Any]]) -> str:
    existing = {normalize_user_id(user.get("id")) for user in users}
    base = normalize_user_id(username)
    if base not in existing:
        return base
    for index in range(2, 1000):
        candidate = f"{base}-{index}"
        if candidate not in existing:
            return candidate
    return f"{base}-{uuid.uuid4().hex[:8]}"
