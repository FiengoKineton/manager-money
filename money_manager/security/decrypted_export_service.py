from __future__ import annotations

import json
import shutil
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from money_manager.config.install_paths import DATA_DIR
from money_manager.config.user_paths import get_current_user_id, get_user_data_dir, normalize_user_id
from money_manager.security.encryption_policy import TEMP_EXPORT_TTL_MINUTES
from money_manager.security.key_manager import unlock_dek
from money_manager.security.secure_storage import read_binary_secure
from money_manager.security.session_vault import unlock_user
from money_manager.users.user_manager import ensure_user_data_folder

EXPORT_METADATA = "export_metadata.json"
EXPORT_ZIP_NAME = "user_data_decrypted.zip"
USER_DATA_PREFIX = "user_data"
EXCLUDED_TOP_LEVEL = {"cache", "plots", "backups"}
EXPIRED_METADATA_DIR = "_expired_metadata"


class DecryptedExportError(RuntimeError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def temp_export_root() -> Path:
    root = DATA_DIR / "_system" / "temp_exports"
    root.mkdir(parents=True, exist_ok=True)
    return root


def user_temp_export_root(user_id: str | None = None) -> Path:
    safe_id = normalize_user_id(user_id or get_current_user_id())
    path = temp_export_root() / safe_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def cleanup_expired_decrypted_exports() -> dict[str, Any]:
    root = temp_export_root()
    now = utc_now()
    scanned = 0
    deleted = 0
    errors: list[str] = []
    for metadata_path in sorted(root.glob("*/*/" + EXPORT_METADATA)):
        scanned += 1
        export_dir = metadata_path.parent
        try:
            metadata = _read_metadata(metadata_path)
            expires_at = _parse_time(metadata.get("expires_at"))
            if expires_at is None or expires_at <= now or metadata.get("status") in {"cancelled", "expired", "deleted"}:
                metadata["status"] = "expired"
                metadata["deleted_at"] = iso(now)
                _write_metadata(metadata_path, metadata)
                _archive_deleted_metadata(metadata)
                shutil.rmtree(export_dir, ignore_errors=True)
                deleted += 1
        except Exception as exc:
            errors.append(f"{metadata_path}: {exc}")
    # Also remove orphan export folders older than the TTL window.
    for export_dir in sorted(root.glob("*/*")):
        if not export_dir.is_dir():
            continue
        if export_dir.name == EXPIRED_METADATA_DIR:
            continue
        metadata_path = export_dir / EXPORT_METADATA
        if metadata_path.exists():
            continue
        try:
            age_seconds = now.timestamp() - export_dir.stat().st_mtime
            if age_seconds > max(60, TEMP_EXPORT_TTL_MINUTES * 60):
                shutil.rmtree(export_dir, ignore_errors=True)
                deleted += 1
        except Exception as exc:
            errors.append(f"{export_dir}: {exc}")
    return {"scanned": scanned, "deleted": deleted, "errors": errors, "root": str(root)}


def create_decrypted_export(user_id: str, password: str) -> dict[str, Any]:
    safe_id = normalize_user_id(user_id)
    if not password:
        raise DecryptedExportError("Password confirmation is required.")
    cleanup_expired_decrypted_exports()
    # Validate password first. unlock_user also stores the DEK for read_binary_secure.
    unlock_dek(safe_id, password)
    unlock_user(safe_id, password)
    ensure_user_data_folder(safe_id, create_files=True)

    export_id = uuid.uuid4().hex
    export_dir = _safe_child(user_temp_export_root(safe_id), export_id)
    export_dir.mkdir(parents=True, exist_ok=False)
    plain_root = export_dir / USER_DATA_PREFIX
    plain_root.mkdir(parents=True, exist_ok=True)
    zip_path = export_dir / EXPORT_ZIP_NAME
    created_at = utc_now()
    expires_at = created_at + timedelta(minutes=TEMP_EXPORT_TTL_MINUTES)

    metadata = {
        "export_id": export_id,
        "user_id": safe_id,
        "created_at": iso(created_at),
        "expires_at": iso(expires_at),
        "downloaded_at": None,
        "status": "active",
        "ttl_minutes": TEMP_EXPORT_TTL_MINUTES,
        "zip_path": str(zip_path),
        "active_data_remains_encrypted": True,
    }

    try:
        count = _materialize_decrypted_user_data(safe_id, plain_root)
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("README.txt", _export_warning_text(expires_at))
            for path in sorted(plain_root.rglob("*")):
                if path.is_file():
                    archive.write(path, f"{USER_DATA_PREFIX}/{path.relative_to(plain_root).as_posix()}")
        metadata["file_count"] = count
        metadata["zip_size_bytes"] = zip_path.stat().st_size if zip_path.exists() else 0
        _write_metadata(export_dir / EXPORT_METADATA, metadata)
        return _public_metadata(metadata)
    except Exception:
        shutil.rmtree(export_dir, ignore_errors=True)
        raise


def get_decrypted_export(user_id: str, export_id: str) -> dict[str, Any]:
    safe_id = normalize_user_id(user_id)
    export_dir = _safe_child(user_temp_export_root(safe_id), _safe_export_id(export_id))
    metadata_path = export_dir / EXPORT_METADATA
    if not metadata_path.exists():
        raise FileNotFoundError("Export does not exist.")
    metadata = _read_metadata(metadata_path)
    if normalize_user_id(metadata.get("user_id")) != safe_id:
        raise PermissionError("Export belongs to another user.")
    expires_at = _parse_time(metadata.get("expires_at"))
    if metadata.get("status") != "active" or expires_at is None or expires_at <= utc_now():
        metadata["status"] = "expired"
        metadata["deleted_at"] = iso(utc_now())
        _write_metadata(metadata_path, metadata)
        _archive_deleted_metadata(metadata)
        shutil.rmtree(export_dir, ignore_errors=True)
        raise FileNotFoundError("Export expired.")
    zip_path = _safe_child(export_dir, EXPORT_ZIP_NAME)
    if not zip_path.exists() or not zip_path.is_file():
        raise FileNotFoundError("Export ZIP is missing.")
    metadata["zip_path"] = str(zip_path)
    return metadata


def mark_decrypted_export_downloaded(user_id: str, export_id: str) -> None:
    try:
        metadata = get_decrypted_export(user_id, export_id)
        metadata_path = _safe_child(user_temp_export_root(user_id), _safe_export_id(export_id)) / EXPORT_METADATA
        metadata["downloaded_at"] = metadata.get("downloaded_at") or iso(utc_now())
        _write_metadata(metadata_path, metadata)
    except Exception:
        pass


def cancel_decrypted_export(user_id: str, export_id: str) -> bool:
    safe_id = normalize_user_id(user_id)
    export_dir = _safe_child(user_temp_export_root(safe_id), _safe_export_id(export_id))
    if not export_dir.exists():
        return False
    try:
        metadata_path = export_dir / EXPORT_METADATA
        if metadata_path.exists():
            metadata = _read_metadata(metadata_path)
            metadata["status"] = "cancelled"
            metadata["deleted_at"] = iso(utc_now())
            _write_metadata(metadata_path, metadata)
            _archive_deleted_metadata(metadata)
    finally:
        shutil.rmtree(export_dir, ignore_errors=True)
    return True


def active_exports_for_user(user_id: str) -> list[dict[str, Any]]:
    safe_id = normalize_user_id(user_id)
    cleanup_expired_decrypted_exports()
    rows: list[dict[str, Any]] = []
    root = user_temp_export_root(safe_id)
    for metadata_path in sorted(root.glob("*/" + EXPORT_METADATA), reverse=True):
        try:
            metadata = _read_metadata(metadata_path)
            if metadata.get("status") == "active" and _parse_time(metadata.get("expires_at")) and _parse_time(metadata.get("expires_at")) > utc_now():
                rows.append(_public_metadata(metadata))
        except Exception:
            continue
    return rows


def _materialize_decrypted_user_data(user_id: str, plain_root: Path) -> int:
    user_dir = get_user_data_dir(user_id)
    count = 0
    for source in sorted(user_dir.rglob("*")):
        if not source.is_file():
            continue
        relative = source.relative_to(user_dir)
        if _is_excluded(relative):
            continue
        target = _safe_child(plain_root, relative.as_posix())
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(read_binary_secure(source, user_id=user_id))
        count += 1
    return count


def _is_excluded(relative: Path) -> bool:
    return bool(relative.parts and relative.parts[0] in EXCLUDED_TOP_LEVEL)


def _safe_export_id(value: str) -> str:
    text = str(value or "").strip()
    if not text or any(ch not in "0123456789abcdef" for ch in text) or len(text) not in {32, 64}:
        raise ValueError("Invalid export id.")
    return text


def _safe_child(base: Path, relative: str) -> Path:
    root = base.resolve()
    path = PurePosixPath(str(relative or ""))
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("Unsafe export path.")
    candidate = root / path
    resolved = candidate.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError("Export path traversal blocked.")
    return resolved


def _archive_deleted_metadata(metadata: dict[str, Any]) -> None:
    """Keep a tiny non-sensitive tombstone proving an export expired/cancelled."""
    try:
        safe_id = normalize_user_id(metadata.get("user_id"))
        export_id = _safe_export_id(str(metadata.get("export_id") or ""))
        archive_dir = user_temp_export_root(safe_id) / EXPIRED_METADATA_DIR
        archive_dir.mkdir(parents=True, exist_ok=True)
        public = _public_metadata(metadata)
        public["deleted_at"] = metadata.get("deleted_at")
        public["status"] = metadata.get("status", public.get("status"))
        _write_metadata(archive_dir / f"{export_id}.json", public)
    except Exception:
        pass


def _read_metadata(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise DecryptedExportError("Export metadata is invalid.") from exc
    if not isinstance(payload, dict):
        raise DecryptedExportError("Export metadata is invalid.")
    return payload


def _write_metadata(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _parse_time(value: Any) -> datetime | None:
    try:
        text = str(value or "").replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _public_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    export_id = str(metadata.get("export_id") or "")
    return {
        "export_id": export_id,
        "user_id": normalize_user_id(metadata.get("user_id")),
        "created_at": metadata.get("created_at", ""),
        "expires_at": metadata.get("expires_at", ""),
        "downloaded_at": metadata.get("downloaded_at"),
        "status": metadata.get("status", ""),
        "ttl_minutes": int(metadata.get("ttl_minutes") or TEMP_EXPORT_TTL_MINUTES),
        "file_count": int(metadata.get("file_count") or 0),
        "zip_size_bytes": int(metadata.get("zip_size_bytes") or 0),
    }


def _export_warning_text(expires_at: datetime) -> str:
    return (
        "Money Manager decrypted export\n\n"
        "This ZIP contains decrypted personal/financial data. "
        "The app will delete its temporary export copy after the expiry time, "
        "but it cannot delete copies you already downloaded.\n\n"
        f"Temporary app-side expiry: {iso(expires_at)}\n"
    )
