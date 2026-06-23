from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from money_manager.cache.cache_store import cache_inventory
from money_manager.config.install_paths import BACKUPS_DIR, LOGS_DIR, SYSTEM_DIR
from money_manager.config.user_paths import get_user_data_dir, normalize_user_id
from money_manager.security.encryption_service import is_file_encrypted
from money_manager.security.encryption_migration_service import sensitive_paths_for_user
from money_manager.security.key_manager import is_encryption_enabled, load_security_metadata
from money_manager.security.secure_storage import read_binary_secure
from money_manager.security.session_vault import vault_status
from money_manager.storage.data_file_service import resolve_definition_path
from money_manager.storage.data_registry import user_file_definitions


def verify_user_encryption(user_id: str) -> dict[str, Any]:
    safe_id = normalize_user_id(user_id)
    user_dir = get_user_data_dir(safe_id)
    vault = vault_status(safe_id)
    enabled = is_encryption_enabled(safe_id)
    files: list[dict[str, Any]] = []
    plaintext: list[str] = []
    encrypted: list[str] = []
    corrupt: list[dict[str, str]] = []
    skipped: list[str] = []

    for path in sensitive_paths_for_user(safe_id):
        if not path.exists() or not path.is_file():
            skipped.append(str(path))
            continue
        row = {"path": str(path), "encrypted": False, "readable": None, "error": ""}
        row["encrypted"] = is_file_encrypted(path)
        if row["encrypted"]:
            encrypted.append(str(path))
            if vault.get("unlocked"):
                try:
                    read_binary_secure(path, user_id=safe_id)
                    row["readable"] = True
                except Exception as exc:
                    row["readable"] = False
                    row["error"] = str(exc)
                    corrupt.append({"path": str(path), "error": str(exc)})
            else:
                row["readable"] = None
        else:
            plaintext.append(str(path))
            row["readable"] = True
        files.append(row)

    cache_info = cache_inventory(user_id=safe_id)
    documents_plaintext = [path for path in plaintext if "/documents/" in path.replace("\\", "/")]
    documents_encrypted = [path for path in encrypted if "/documents/" in path.replace("\\", "/")]

    return {
        "user_id": safe_id,
        "active_data_path": str(user_dir),
        "encryption_enabled": enabled,
        "vault": vault,
        "files_scanned": len(files),
        "sensitive_files_scanned": len(files),
        "encrypted_count": len(encrypted),
        "sensitive_files_encrypted": len(encrypted),
        "plaintext_count": len(plaintext),
        "sensitive_files_plaintext": len(plaintext),
        "corrupt_count": len(corrupt),
        "corrupt_encrypted_files": corrupt,
        "plaintext_files": plaintext,
        "encrypted_files": encrypted,
        "skipped_files": skipped,
        "cache_encrypted_count": int(cache_info.get("encrypted_sensitive_count") or 0),
        "cache_plaintext_count": int(cache_info.get("plaintext_sensitive_count") or 0),
        "documents_encrypted_count": len(documents_encrypted),
        "documents_plaintext_count": len(documents_plaintext),
        "cache": cache_info,
        "files": files,
        "success": enabled and not plaintext and not corrupt,
    }


def security_audit(user_id: str) -> dict[str, Any]:
    safe_id = normalize_user_id(user_id)
    metadata = load_security_metadata(safe_id, create=True)
    verification = verify_user_encryption(safe_id)
    enabled = bool(verification["encryption_enabled"])
    checks: list[dict[str, Any]] = []

    checks.append(_check("encryption_enabled", "Protected" if enabled else "Action needed", "Encryption enabled" if enabled else "Encryption is disabled for this user."))
    checks.append(_check("security_metadata", "Protected" if metadata else "Action needed", "Security metadata is present." if metadata else "Security metadata is missing."))

    if verification["plaintext_count"]:
        checks.append(_check("sensitive_files_plaintext", "Action needed", f"{verification['plaintext_count']} sensitive files are still plaintext.", verification["plaintext_files"][:10]))
    else:
        checks.append(_check("sensitive_files_plaintext", "Protected", f"Sensitive files encrypted/clean: {verification['encrypted_count']} encrypted."))

    if verification["corrupt_count"]:
        checks.append(_check("corrupt_encrypted_files", "Action needed", f"{verification['corrupt_count']} encrypted files could not be decrypted.", [row["path"] for row in verification["corrupt_encrypted_files"][:10]]))
    else:
        checks.append(_check("corrupt_encrypted_files", "Protected", "No corrupt encrypted files detected."))

    checks.append(_check("documents_encrypted", "Action needed" if verification["documents_plaintext_count"] else "Protected", f"Documents encrypted: {verification['documents_encrypted_count']}; plaintext: {verification['documents_plaintext_count']}."))
    checks.append(_check("vault_status", "Protected" if verification["vault"].get("unlocked") or not enabled else "Warning", "Vault is unlocked." if verification["vault"].get("unlocked") else "Vault is locked or encryption is disabled."))

    users_json = SYSTEM_DIR / "users.json"
    checks.append(_check("users_json", "Warning", "users.json is intentionally plaintext so login can find users and verify password hashes before vault unlock.", [str(users_json)]))

    log_warnings = _scan_logs_for_sensitive_tokens()
    checks.append(_check("logs_sensitive_values", "Warning" if log_warnings else "Protected", "Possible sensitive values found in logs." if log_warnings else "No obvious IBAN/account leaks found in logs.", log_warnings[:10]))

    backup_notes = _backup_status(safe_id)
    checks.append(_check("backups", backup_notes["status"], backup_notes["message"], backup_notes.get("details", [])))

    cache_info = verification["cache"]
    cache_status_label = "Protected" if int(cache_info.get("plaintext_sensitive_count") or 0) == 0 else "Action needed"
    cache_message = (
        f"Cache location: {cache_info.get('location')}. Size: {cache_info.get('size_label')}. "
        f"Entries: {cache_info.get('entry_count')}. Stale: {cache_info.get('stale_count')}. "
        f"Sensitive encrypted: {cache_info.get('encrypted_sensitive_count')}; plaintext: {cache_info.get('plaintext_sensitive_count')}."
    )
    checks.append(_check("cache_sensitive_data", cache_status_label, cache_message, [str(cache_info.get("location"))]))

    return {
        "user_id": safe_id,
        "active_data_path": str(get_user_data_dir(safe_id)),
        "encryption_enabled": enabled,
        "vault": verification["vault"],
        "metadata": {k: v for k, v in metadata.items() if k not in {"encrypted_dek", "dek_nonce"}},
        "verification": verification,
        "checks": checks,
        "summary": {
            "protected": sum(1 for c in checks if c["status"] == "Protected"),
            "warnings": sum(1 for c in checks if c["status"] == "Warning"),
            "action_needed": sum(1 for c in checks if c["status"] == "Action needed"),
        },
    }


def _check(name: str, status: str, message: str, details: list[str] | None = None) -> dict[str, Any]:
    return {"name": name, "status": status, "message": message, "details": details or []}


def _scan_logs_for_sensitive_tokens() -> list[str]:
    warnings: list[str] = []
    if not LOGS_DIR.exists():
        return warnings
    pattern = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{8,30}\b|\b\d{1,3}(?:[.,]\d{2})\s?(?:EUR|€)\b", re.I)
    for path in LOGS_DIR.rglob("*.log"):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")[:200_000]
        except OSError:
            continue
        if pattern.search(text):
            warnings.append(str(path))
    return warnings


def _backup_status(user_id: str) -> dict[str, Any]:
    user_backup_dir = BACKUPS_DIR / normalize_user_id(user_id)
    if not user_backup_dir.exists():
        return {"status": "Protected", "message": "No backup ZIPs found in the standard backup folder."}
    zip_files = sorted(user_backup_dir.glob("*.zip"))
    if not zip_files:
        return {"status": "Protected", "message": "No backup ZIPs found in the standard backup folder."}
    return {"status": "Warning", "message": f"{len(zip_files)} backup ZIP(s) exist. Encrypted backups preserve encrypted files. Decrypted temporary exports expire and are deleted.", "details": [str(path) for path in zip_files[-5:]]}
