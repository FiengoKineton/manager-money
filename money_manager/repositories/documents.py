from __future__ import annotations

import mimetypes
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4


from money_manager.config import (
    ALLOWED_DOCUMENT_EXTENSIONS,
    DOCUMENT_FOLDERS,
)
from money_manager.config.user_paths import user_documents_dir
from money_manager.security.protection_manager import safe_join
from money_manager.security.secure_storage import (
    read_json_secure,
    secure_delete,
    write_binary_secure,
    write_json_secure,
)

DOCUMENT_METADATA_LOGICAL_NAME = "documents_metadata"
DOCUMENT_METADATA_DEFAULT = {"schema_version": 1, "documents": []}
MAX_DOCUMENT_UPLOAD_BYTES = 50 * 1024 * 1024
_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_WINDOWS_NAMES = {"CON", "PRN", "AUX", "NUL", *{f"COM{i}" for i in range(1, 10)}, *{f"LPT{i}" for i in range(1, 10)}}
_DATE_PATTERNS = (
    re.compile(r"(?<!\d)(?P<year>20\d{2})[-_. ](?P<month>0?[1-9]|1[0-2])(?:[-_. ](?P<day>0?[1-9]|[12]\d|3[01]))?(?!\d)"),
    re.compile(r"(?<!\d)(?P<day>0?[1-9]|[12]\d|3[01])[-_. ](?P<month>0?[1-9]|1[0-2])[-_. ](?P<year>20\d{2})(?!\d)"),
)


def is_allowed_folder(folder: str) -> bool:
    return folder in DOCUMENT_FOLDERS


def is_allowed_document(filename: str) -> bool:
    """Return True only for file types the document viewer is allowed to expose."""
    return Path(filename).suffix.lower() in ALLOWED_DOCUMENT_EXTENSIONS


def folder_path(folder: str) -> Path:
    if not is_allowed_folder(folder):
        raise ValueError(f"Invalid document folder: {folder}")

    return safe_join(user_documents_dir(), folder)


def document_path(folder: str, filename: str) -> Path:
    if not is_allowed_document(filename):
        raise ValueError(f"Invalid document file: {filename}")
    return safe_join(folder_path(folder), filename)


def list_files(folder: str) -> list[str]:
    """List folder documents from newest to oldest.

    Date-like filenames (for example ``2026-03.pdf``) are ordered by that date.
    Other files use their stored upload timestamp and finally their filesystem
    modification time, so newly uploaded documents also appear immediately.
    """
    path = folder_path(folder)

    if not path.exists():
        return []

    metadata = _metadata_by_file(folder)
    files = [
        item
        for item in path.iterdir()
        if item.is_file() and is_allowed_document(item.name)
    ]
    files.sort(
        key=lambda item: (
            _document_sort_timestamp(item, metadata.get(item.name)),
            item.name.casefold(),
        ),
        reverse=True,
    )
    return [item.name for item in files]


def save_document(
    folder: str,
    original_filename: str,
    data: bytes,
    *,
    content_type: str = "",
) -> dict[str, Any]:
    """Persist a document and index it in the secure document metadata store."""
    if not is_allowed_folder(folder):
        raise ValueError("Select one of the available document folders.")

    original_name = Path(str(original_filename or "").replace("\\", "/")).name.strip()
    if not original_name:
        raise ValueError("Choose a document to upload.")

    extension = Path(original_name).suffix.lower()
    if extension not in ALLOWED_DOCUMENT_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_DOCUMENT_EXTENSIONS))
        raise ValueError(f"This file type is not supported. Allowed types: {allowed}.")

    payload = bytes(data or b"")
    if not payload:
        raise ValueError("The selected document is empty.")
    if len(payload) > MAX_DOCUMENT_UPLOAD_BYTES:
        max_mb = MAX_DOCUMENT_UPLOAD_BYTES // (1024 * 1024)
        raise ValueError(f"The document is too large. Maximum size: {max_mb} MB.")

    safe_name = _safe_storage_filename(original_name, extension)

    target_folder = folder_path(folder)
    target_folder.mkdir(parents=True, exist_ok=True)
    stored_name = _unique_filename(target_folder, safe_name)
    target = document_path(folder, stored_name)
    uploaded_at = datetime.now(timezone.utc).isoformat()

    write_binary_secure(
        target,
        payload,
        original_filename=original_name,
        content_type=content_type or mimetypes.guess_type(stored_name)[0] or "application/octet-stream",
    )

    try:
        metadata = _load_metadata()
        document = {
            "id": uuid4().hex,
            "folder": folder,
            "filename": stored_name,
            "original_filename": original_name,
            "content_type": content_type or mimetypes.guess_type(stored_name)[0] or "application/octet-stream",
            "size_bytes": len(payload),
            "uploaded_at": uploaded_at,
        }
        metadata["documents"].append(document)
        write_json_secure(DOCUMENT_METADATA_LOGICAL_NAME, metadata)
    except Exception:
        secure_delete(None, target)
        raise

    return document


def _load_metadata() -> dict[str, Any]:
    raw = read_json_secure(DOCUMENT_METADATA_LOGICAL_NAME, default=DOCUMENT_METADATA_DEFAULT)
    if not isinstance(raw, Mapping):
        raw = DOCUMENT_METADATA_DEFAULT

    documents = raw.get("documents", [])
    if not isinstance(documents, list):
        documents = []

    try:
        schema_version = int(raw.get("schema_version") or 1)
    except (TypeError, ValueError):
        schema_version = 1

    return {
        "schema_version": schema_version,
        "documents": [dict(item) for item in documents if isinstance(item, Mapping)],
    }


def _metadata_by_file(folder: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in _load_metadata().get("documents", []):
        if item.get("folder") != folder:
            continue
        filename = str(item.get("filename") or "")
        if filename:
            result[filename] = item
    return result


def _safe_storage_filename(filename: str, extension: str) -> str:
    cleaned = _INVALID_FILENAME_CHARS.sub("_", filename).strip().rstrip(". ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    stem = Path(cleaned).stem.strip().rstrip(". ") or "document"
    if stem.upper() in _RESERVED_WINDOWS_NAMES:
        stem = f"_{stem}"

    max_stem_length = max(1, 180 - len(extension))
    stem = stem[:max_stem_length].rstrip(". ") or "document"
    return f"{stem}{extension}"


def _unique_filename(directory: Path, filename: str) -> str:
    candidate = filename
    stem = Path(filename).stem or "document"
    suffix = Path(filename).suffix.lower()
    counter = 2
    while safe_join(directory, candidate).exists():
        candidate = f"{stem} ({counter}){suffix}"
        counter += 1
    return candidate


def _document_sort_timestamp(path: Path, metadata: Mapping[str, Any] | None) -> float:
    filename_date = _date_from_filename(path.stem)
    if filename_date is not None:
        return filename_date.timestamp()

    uploaded_at = str((metadata or {}).get("uploaded_at") or "").strip()
    if uploaded_at:
        try:
            parsed = datetime.fromisoformat(uploaded_at.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp()
        except ValueError:
            pass

    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _date_from_filename(value: str) -> datetime | None:
    for pattern in _DATE_PATTERNS:
        match = pattern.search(value)
        if not match:
            continue
        parts = match.groupdict()
        try:
            return datetime(
                int(parts["year"]),
                int(parts["month"]),
                int(parts.get("day") or 1),
                tzinfo=timezone.utc,
            )
        except (TypeError, ValueError):
            continue
    return None
