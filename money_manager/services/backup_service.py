from __future__ import annotations

import json
import shutil
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO

from money_manager.config.install_paths import BACKUPS_DIR
from money_manager.config.user_paths import get_current_user_id, get_user_data_dir, normalize_user_id
from money_manager.security.key_manager import is_encryption_enabled, metadata_path, unlock_dek
from money_manager.security.secure_storage import read_binary_secure
from money_manager.services.account_integrity_service import full_integrity_report
from money_manager.services.schema_service import ensure_user_schema
from money_manager.users.user_manager import ensure_user_data_folder

BACKUP_SCHEMA_VERSION = 1
BACKUP_APP_NAME = "money_manager"
BACKUP_METADATA = "backup_metadata.json"
USER_DATA_PREFIX = "user_data"
EXCLUDED_TOP_LEVEL_DIRS = {"cache", "plots", "backups"}


class BackupValidationError(ValueError):
    """Raised when a ZIP is not a safe Money Manager backup."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def current_backup_filename(user_id: str | None = None, *, purpose: str = "backup") -> str:
    safe_user_id = normalize_user_id(user_id or get_current_user_id())
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    suffix = f"_{purpose}" if purpose and purpose != "backup" else ""
    return f"money_manager_backup_{safe_user_id}_{stamp}{suffix}.zip"


def export_current_user_backup(
    user_id: str | None = None,
    *,
    destination_dir: Path | None = None,
    purpose: str = "backup",
    mode: str = "encrypted",
    plain_export_password: str | None = None,
) -> Path:
    safe_user_id = normalize_user_id(user_id or get_current_user_id())
    user_dir = get_user_data_dir(safe_user_id)
    ensure_user_data_folder(safe_user_id, create_files=True)
    ensure_user_schema(safe_user_id)
    mode = str(mode or "encrypted").strip().casefold()
    if mode not in {"encrypted", "plain"}:
        raise BackupValidationError("Unsupported backup mode.")
    encryption_active = is_encryption_enabled(safe_user_id)
    if mode == "plain" and encryption_active:
        if not plain_export_password:
            raise BackupValidationError("Plain export requires password confirmation.")
        unlock_dek(safe_user_id, plain_export_password)

    target_dir = destination_dir or (BACKUPS_DIR / safe_user_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / current_backup_filename(safe_user_id, purpose=purpose)

    metadata = {
        "schema_version": BACKUP_SCHEMA_VERSION,
        "app": BACKUP_APP_NAME,
        "created_at": utc_now(),
        "source_user_id": safe_user_id,
        "backup_name": target.name,
        "backup_mode": mode,
        "encryption_enabled_at_export": encryption_active,
        "backup_contents": "current-user data only; auth/password hashes excluded",
        "security_metadata_included": bool(encryption_active and mode == "encrypted"),
        "plain_export_warning": "Plain exports contain decrypted sensitive files." if mode == "plain" else "",
        "excluded_by_default": sorted(EXCLUDED_TOP_LEVEL_DIRS),
    }

    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(BACKUP_METADATA, json.dumps(metadata, indent=2, ensure_ascii=False))
        if encryption_active and mode == "encrypted":
            sec_path = metadata_path(safe_user_id)
            if sec_path.exists():
                archive.write(sec_path, "security/user_security_metadata.json")
        for path in sorted(user_dir.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(user_dir)
            if _is_excluded(relative):
                continue
            arcname = f"{USER_DATA_PREFIX}/{relative.as_posix()}"
            if mode == "plain":
                archive.writestr(arcname, read_binary_secure(path, user_id=safe_user_id))
            else:
                archive.write(path, arcname)
    return target


def restore_current_user_backup(
    source: str | Path | BinaryIO,
    user_id: str | None = None,
    *,
    mode: str = "replace",
) -> dict[str, Any]:
    if mode not in {"replace", "merge"}:
        raise BackupValidationError("Unsupported import mode.")
    # The first implementation treats merge as replacement because replacement
    # is the only safe mode that does not risk duplicating money rows.
    effective_mode = "replace"
    safe_user_id = normalize_user_id(user_id or get_current_user_id())
    user_dir = get_user_data_dir(safe_user_id)
    ensure_user_data_folder(safe_user_id, create_files=True)

    upload_path = _materialize_source(source)
    try:
        validation = validate_backup_zip(upload_path)
        auto_backup = export_current_user_backup(safe_user_id, purpose="pre_import")
        restored_files = _restore_from_validated_zip(upload_path, user_dir, mode=effective_mode)
        ensure_user_data_folder(safe_user_id, create_files=True)
        # If a decrypted/plain backup was imported while encryption is active,
        # immediately re-encrypt sensitive files through the active secure layer.
        if is_encryption_enabled(safe_user_id):
            try:
                from money_manager.security.encryption_migration_service import sensitive_paths_for_user
                from money_manager.security.secure_storage import encrypt_path_if_needed

                for candidate in sensitive_paths_for_user(safe_user_id):
                    if candidate.exists() and candidate.is_file():
                        encrypt_path_if_needed(candidate, safe_user_id)
            except Exception:
                pass
        ensure_user_schema(safe_user_id)
        integrity_report = full_integrity_report(safe_user_id)
        return {
            "restored_files": restored_files,
            "auto_backup": str(auto_backup),
            "metadata": validation["metadata"],
            "mode": effective_mode,
            "integrity_report": integrity_report,
        }
    finally:
        try:
            upload_path.unlink(missing_ok=True)
        except OSError:
            pass


def validate_backup_zip(path: Path) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(path, "r") as archive:
            members = archive.infolist()
            names = [member.filename for member in members]
            if BACKUP_METADATA not in names:
                raise BackupValidationError("This ZIP is missing backup_metadata.json.")
            metadata = _read_metadata(archive)
            if metadata.get("app") != BACKUP_APP_NAME:
                raise BackupValidationError("This is not a Money Manager backup.")
            if int(metadata.get("schema_version") or 0) < 1:
                raise BackupValidationError("Unsupported backup schema version.")
            files = []
            for member in members:
                if member.is_dir():
                    continue
                safe = _safe_member_name(member.filename)
                if safe == BACKUP_METADATA:
                    continue
                if safe.startswith("security/"):
                    if safe != "security/user_security_metadata.json":
                        raise BackupValidationError(f"Unexpected security metadata path: {member.filename}")
                    continue
                if not safe.startswith(f"{USER_DATA_PREFIX}/"):
                    raise BackupValidationError(f"Unexpected backup path: {member.filename}")
                relative = safe.removeprefix(f"{USER_DATA_PREFIX}/")
                if not relative:
                    raise BackupValidationError("Empty user_data path in backup.")
                if relative.split("/", 1)[0] in EXCLUDED_TOP_LEVEL_DIRS:
                    raise BackupValidationError(f"Backup contains excluded runtime folder: {relative}")
                if relative.startswith("documents/"):
                    _validate_document_relative_path(relative)
                if relative == "payment_methods.json":
                    _validate_imported_payment_methods_payload(archive.read(member))
                files.append(relative)
            return {"metadata": metadata, "files": files, "file_count": len(files)}
    except zipfile.BadZipFile as exc:
        raise BackupValidationError("Uploaded file is not a valid ZIP archive.") from exc


def _restore_from_validated_zip(path: Path, user_dir: Path, *, mode: str) -> int:
    if mode != "replace":
        raise BackupValidationError("Only replacement import is currently supported.")

    with tempfile.TemporaryDirectory(prefix="money_manager_import_") as temp_name:
        temp_root = Path(temp_name)
        extracted_user_data = temp_root / USER_DATA_PREFIX
        extracted_user_data.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(path, "r") as archive:
            for member in archive.infolist():
                if member.is_dir() or member.filename == BACKUP_METADATA:
                    continue
                safe = _safe_member_name(member.filename)
                if safe.startswith("security/"):
                    continue
                relative = safe.removeprefix(f"{USER_DATA_PREFIX}/")
                target = _safe_child(extracted_user_data, relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member, "r") as source_handle, target.open("wb") as target_handle:
                    shutil.copyfileobj(source_handle, target_handle)

        restored_count = sum(1 for item in extracted_user_data.rglob("*") if item.is_file())
        _replace_user_folder(user_dir, extracted_user_data)
        return restored_count


def _replace_user_folder(user_dir: Path, extracted_user_data: Path) -> None:
    user_dir.mkdir(parents=True, exist_ok=True)
    backups_dir = user_dir / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)

    for item in list(user_dir.iterdir()):
        if item.name == "backups":
            continue
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink(missing_ok=True)

    for source in extracted_user_data.rglob("*"):
        relative = source.relative_to(extracted_user_data)
        target = _safe_child(user_dir, relative.as_posix())
        if source.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _materialize_source(source: str | Path | BinaryIO) -> Path:
    if isinstance(source, (str, Path)):
        return Path(source)
    handle = tempfile.NamedTemporaryFile(prefix="money_manager_upload_", suffix=".zip", delete=False)
    with handle:
        shutil.copyfileobj(source, handle)
    return Path(handle.name)


def _read_metadata(archive: zipfile.ZipFile) -> dict[str, Any]:
    try:
        raw = archive.read(BACKUP_METADATA)
        metadata = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise BackupValidationError("Backup metadata is invalid.") from exc
    if not isinstance(metadata, dict):
        raise BackupValidationError("Backup metadata must be a JSON object.")
    return metadata


def _safe_member_name(name: str) -> str:
    text = str(name or "").strip()
    if not text or text.startswith("/") or "\\" in text:
        raise BackupValidationError(f"Unsafe backup path: {name}")
    path = PurePosixPath(text)
    if path.is_absolute():
        raise BackupValidationError(f"Unsafe backup path: {name}")
    parts = path.parts
    if any(part in {"", ".", ".."} for part in parts):
        raise BackupValidationError(f"Unsafe backup path: {name}")
    if parts and ":" in parts[0]:
        raise BackupValidationError(f"Unsafe backup path: {name}")
    return path.as_posix()


def _validate_document_relative_path(relative: str) -> None:
    safe = _safe_member_name(relative)
    if not safe.startswith("documents/"):
        raise BackupValidationError("Document path must stay inside documents/.")
    if safe == "documents":
        raise BackupValidationError("Document path is empty.")


def _safe_child(base: Path, relative: str) -> Path:
    root = base.resolve()
    candidate = root / PurePosixPath(_safe_member_name(relative))
    resolved = candidate.resolve()
    if resolved != root and root not in resolved.parents:
        raise BackupValidationError(f"Unsafe restore path: {relative}")
    return resolved


def _is_excluded(relative: Path) -> bool:
    if not relative.parts:
        return True
    return relative.parts[0] in EXCLUDED_TOP_LEVEL_DIRS


def _validate_imported_payment_methods_payload(raw: bytes) -> None:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise BackupValidationError("payment_methods.json in backup is not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise BackupValidationError("payment_methods.json in backup must be a JSON object.")
    methods = payload.get("payment_methods", [])
    if not isinstance(methods, list):
        raise BackupValidationError("payment_methods.json in backup has invalid payment_methods list.")
    for index, method in enumerate(methods, start=1):
        if not isinstance(method, dict):
            continue
        _reject_path_like_payment_method_values(method, f"payment_methods[{index}]")


def _reject_path_like_payment_method_values(value: Any, label: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key or "").casefold()
            if key_text.endswith("path") or key_text.endswith("file") or key_text.endswith("dir") or key_text.endswith("folder"):
                text = str(child or "")
                if ".." in text or "/" in text or "\\" in text or ":" in text:
                    raise BackupValidationError(f"Imported payment method contains unsafe path-like value at {label}.{key}.")
            _reject_path_like_payment_method_values(child, f"{label}.{key}")
    elif isinstance(value, list):
        for pos, child in enumerate(value, start=1):
            _reject_path_like_payment_method_values(child, f"{label}[{pos}]")
