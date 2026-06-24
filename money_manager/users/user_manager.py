from __future__ import annotations

import uuid
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from money_manager.config.user_paths import SYSTEM_DIR, USERS_DIR, normalize_user_id
from money_manager.security.protection_manager import hash_password, read_json, verify_password, write_json_atomic
from money_manager.storage.data_file_service import ensure_system_files, ensure_user_files
from money_manager.storage.data_migration_service import migrate_flat_data_to_user_folder
from money_manager.storage.data_registry import csv_schemas, flat_migration_filenames, json_defaults

USERS_JSON = SYSTEM_DIR / "users.json"
SCHEMA_VERSION = 1

# Compatibility exports. The central registry owns the actual definitions now.
CSV_SCHEMAS: dict[str, list[str]] = csv_schemas()
JSON_DEFAULTS: dict[str, Any] = json_defaults()
FLAT_DATA_FILENAMES = flat_migration_filenames()
DOCUMENT_METADATA = {"schema_version": 1, "documents": []}

_USERS_LOCK = threading.RLock()
_USERS_CACHE: tuple[int, int, list[dict[str, Any]]] | None = None
_SYSTEM_FILES_READY = False


def _users_stat() -> tuple[int, int]:
    try:
        stat = USERS_JSON.stat()
        return int(stat.st_mtime_ns), int(stat.st_size)
    except OSError:
        return 0, 0


def _ensure_system_files_once() -> None:
    global _SYSTEM_FILES_READY
    if _SYSTEM_FILES_READY:
        return
    with _USERS_LOCK:
        if not _SYSTEM_FILES_READY:
            ensure_system_files()
            _SYSTEM_FILES_READY = True


def clear_users_cache() -> None:
    global _USERS_CACHE
    with _USERS_LOCK:
        _USERS_CACHE = None


def _empty_payload() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "users": []}


def load_users() -> list[dict[str, Any]]:
    global _USERS_CACHE
    _ensure_system_files_once()
    mtime_ns, size = _users_stat()
    with _USERS_LOCK:
        if _USERS_CACHE and _USERS_CACHE[0] == mtime_ns and _USERS_CACHE[1] == size:
            return [dict(user) for user in _USERS_CACHE[2]]

    payload = read_json(USERS_JSON, _empty_payload())
    if not isinstance(payload, dict):
        users_clean: list[dict[str, Any]] = []
    else:
        users = payload.get("users", [])
        users_clean = []
        if isinstance(users, list):
            for user in users:
                if isinstance(user, dict) and user.get("id") and user.get("username"):
                    users_clean.append(dict(user))
    mtime_ns, size = _users_stat()
    with _USERS_LOCK:
        _USERS_CACHE = (mtime_ns, size, [dict(user) for user in users_clean])
    return [dict(user) for user in users_clean]


def save_users(users: list[dict[str, Any]]) -> None:
    SYSTEM_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": SCHEMA_VERSION, "users": users}
    write_json_atomic(USERS_JSON, payload)
    clear_users_cache()


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

    # Encryption is a default storage layer, not an optional afterthought.
    # Enable and unlock the vault before any user JSON/CSV defaults are created,
    # otherwise first-run files would be written as plaintext and migrated later.
    from money_manager.security.key_manager import enable_encryption_metadata
    from money_manager.security.session_vault import unlock_user
    from money_manager.security.encryption_migration_service import migrate_user_to_encrypted_storage

    enable_encryption_metadata(user_id, password)
    unlock_user(user_id, password, remember_in_session=False)

    if first_user:
        migrate_flat_data_to_user(user_id)
        migrate_user_to_encrypted_storage(user_id, password)

    ensure_user_data_folder(user_id, create_files=True)
    _ensure_user_config_files(user_id, user)

    from money_manager.services.preferences_service import update_preferences

    update_preferences({"onboarding_completed": False}, user_id=user_id, allow_future_fields=True)

    users.append(user)
    save_users(users)
    return user


def authenticate_user(username: str, password: str) -> dict[str, Any] | None:
    user = get_user_by_username(username)
    if not user or user.get("active") is False:
        return None
    if not verify_password(password, str(user.get("password_hash") or "")):
        return None
    user_id = str(user.get("id"))
    try:
        from money_manager.security.key_manager import is_encryption_enabled

        ensure_user_data_folder(user_id, create_files=not is_encryption_enabled(user_id))
    except Exception:
        ensure_user_data_folder(user_id, create_files=False)
    return user


def update_user_password(user_id: str, new_password: str) -> None:
    safe_id = normalize_user_id(user_id)
    users = load_users()
    changed = False
    for user in users:
        if normalize_user_id(user.get("id")) == safe_id:
            user["password_hash"] = hash_password(new_password)
            user["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            changed = True
            break
    if not changed:
        raise ValueError("User not found.")
    save_users(users)


def ensure_user_data_folder(user_id: str, create_files: bool = True) -> Path:
    safe_id = normalize_user_id(user_id)
    user_dir = USERS_DIR / safe_id
    user_dir.mkdir(parents=True, exist_ok=True)
    for dirname in ("cache", "plots", "documents"):
        (user_dir / dirname).mkdir(parents=True, exist_ok=True)
    for folder in ("Cedolini", "Tasse - Detrazioni Fiscali"):
        (user_dir / "documents" / folder).mkdir(parents=True, exist_ok=True)
    if create_files:
        ensure_user_files(safe_id)
        _ensure_user_config_files(safe_id, get_user_by_id(safe_id))
        from money_manager.services.schema_service import ensure_user_schema

        ensure_user_schema(safe_id)
    return user_dir


def migrate_flat_data_to_user(user_id: str) -> dict[str, Any]:
    safe_id = normalize_user_id(user_id)
    ensure_user_data_folder(safe_id, create_files=False)
    return migrate_flat_data_to_user_folder(safe_id)


def _ensure_default_data_files(user_dir: Path) -> None:
    # Compatibility shim for older imports/tests. The registry-driven service is
    # now responsible for creating CSV/JSON defaults.
    ensure_user_files(user_dir.name)


def _ensure_user_config_files(user_id: str, user_hint: dict[str, Any] | None = None) -> None:
    """Create or repair per-user backend config JSON files."""
    from money_manager.services.account_config_service import ensure_accounts_config
    from money_manager.services.contact_service import ensure_contacts_config
    from money_manager.services.custom_category_service import ensure_categories_config
    from money_manager.services.document_type_service import ensure_document_types_config
    from money_manager.services.navigation_service import ensure_navigation_config
    from money_manager.services.payment_method_service import ensure_payment_methods_file
    from money_manager.services.preferences_service import ensure_preferences_config
    from money_manager.services.profile_service import ensure_profile_config

    ensure_profile_config(user_id=user_id, user_hint=user_hint)
    ensure_preferences_config(user_id=user_id)
    ensure_categories_config(user_id=user_id)
    ensure_accounts_config(user_id=user_id)
    ensure_payment_methods_file(user_id=user_id)
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
