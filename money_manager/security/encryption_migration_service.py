from __future__ import annotations

from pathlib import Path
from typing import Any

from money_manager.config.user_paths import get_user_data_dir, normalize_user_id
from money_manager.security.encryption_policy import is_sensitive_user_relative_path
from money_manager.security.key_manager import enable_encryption_metadata, is_encryption_enabled
from money_manager.security.session_vault import unlock_user
from money_manager.security.secure_storage import encrypt_path_if_needed, is_path_encrypted, read_binary_secure
from money_manager.services.backup_service import export_current_user_backup
from money_manager.storage.data_file_service import resolve_definition_path
from money_manager.storage.data_registry import user_file_definitions


class EncryptionMigrationError(RuntimeError):
    pass


def sensitive_paths_for_user(user_id: str) -> list[Path]:
    safe_id = normalize_user_id(user_id)
    user_dir = get_user_data_dir(safe_id)
    paths: list[Path] = []
    for definition in user_file_definitions():
        if definition.file_type in {"json", "csv"} and getattr(definition, "encrypted_by_default", False):
            paths.append(resolve_definition_path(definition, user_id=safe_id))
    # Include uploaded documents, profile images, and any future sensitive files
    # under the active user folder that match the central policy.
    if user_dir.exists():
        for path in sorted(user_dir.rglob("*")):
            if not path.is_file():
                continue
            try:
                relative = path.relative_to(user_dir).as_posix()
            except Exception:
                continue
            if is_sensitive_user_relative_path(relative):
                paths.append(path)
    seen: set[Path] = set()
    deduped: list[Path] = []
    for path in paths:
        try:
            resolved = path.resolve()
        except Exception:
            resolved = path
        if resolved not in seen:
            seen.add(resolved)
            deduped.append(path)
    return deduped


def dry_run_encryption(user_id: str) -> dict[str, Any]:
    safe_id = normalize_user_id(user_id)
    rows = []
    for path in sensitive_paths_for_user(safe_id):
        rows.append({
            "path": str(path),
            "exists": path.exists(),
            "encrypted": is_path_encrypted(path) if path.exists() else False,
            "size": path.stat().st_size if path.exists() else 0,
        })
    return {
        "user_id": safe_id,
        "active_data_path": str(get_user_data_dir(safe_id)),
        "encryption_enabled": is_encryption_enabled(safe_id),
        "candidate_count": len(rows),
        "plaintext_count": sum(1 for row in rows if row["exists"] and not row["encrypted"]),
        "files": rows,
    }


def migrate_user_to_encrypted_storage(user_id: str, password: str) -> dict[str, Any]:
    safe_id = normalize_user_id(user_id)
    user_dir = get_user_data_dir(safe_id)
    _metadata, _dek = enable_encryption_metadata(safe_id, password)
    unlock_user(safe_id, password)

    report: dict[str, Any] = {
        "user_id": safe_id,
        "active_data_path": str(user_dir),
        "files_scanned": 0,
        "files_encrypted": 0,
        "files_already_encrypted": 0,
        "files_skipped": [],
        "files_failed": [],
        "plaintext_remaining": [],
        "success": True,
    }

    for path in sensitive_paths_for_user(safe_id):
        report["files_scanned"] += 1
        if not path.exists() or not path.is_file():
            report["files_skipped"].append(str(path))
            continue
        try:
            if is_path_encrypted(path):
                read_binary_secure(path, user_id=safe_id)
                report["files_already_encrypted"] += 1
                continue
            encrypted = encrypt_path_if_needed(path, safe_id)
            if encrypted:
                read_binary_secure(path, user_id=safe_id)  # verification decrypt
                report["files_encrypted"] += 1
            elif not is_path_encrypted(path):
                report["plaintext_remaining"].append(str(path))
        except Exception as exc:
            report["files_failed"].append({"path": str(path), "error": str(exc)})

    # Sensitive cache is disposable. Clear it after migration so old plaintext
    # computed data cannot survive the switch to encrypted source files.
    try:
        from money_manager.cache.cache_store import clear_user_cache

        report["cache_files_deleted"] = clear_user_cache(user_id=safe_id)
    except Exception as exc:
        report["cache_clear_error"] = str(exc)

    for path in sensitive_paths_for_user(safe_id):
        if path.exists() and path.is_file() and not is_path_encrypted(path):
            if str(path) not in report["plaintext_remaining"]:
                report["plaintext_remaining"].append(str(path))

    report["success"] = not report["files_failed"] and not report["plaintext_remaining"]
    return report


def enable_encryption_for_user(user_id: str, password: str, *, create_backup: bool = True) -> dict[str, Any]:
    safe_id = normalize_user_id(user_id)
    backup_path = None
    if create_backup:
        backup_path = export_current_user_backup(safe_id, purpose="pre_encryption")
    report = migrate_user_to_encrypted_storage(safe_id, password)
    if not report.get("success"):
        raise EncryptionMigrationError(f"Encryption migration failed: {report}")
    return {
        "ok": True,
        "user_id": safe_id,
        "backup_path": str(backup_path) if backup_path else "",
        "encrypted_files": report.get("files_encrypted", 0),
        "already_encrypted": report.get("files_already_encrypted", 0),
        "failed": report.get("files_failed", []),
        "migration_report": report,
    }
