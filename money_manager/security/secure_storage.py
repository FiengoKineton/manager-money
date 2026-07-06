from __future__ import annotations

import csv
import sys
import json
import mimetypes
import os
from io import StringIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Iterable

from money_manager.config.install_paths import USERS_DIR
from money_manager.config.user_paths import get_current_user_id, normalize_user_id
from money_manager.security.encryption_service import decrypt_bytes, encrypt_bytes, is_encrypted_bytes, is_file_encrypted
from money_manager.security.encryption_policy import ENCRYPTION_REQUIRED_FOR_USER_DATA, is_sensitive_user_relative_path
from money_manager.security.key_manager import is_encryption_enabled
from money_manager.security.session_vault import require_dek
from money_manager.storage.data_registry import definition_by_name, definition_for_filename



def _raise_csv_field_limit() -> None:
    limit = sys.maxsize
    while limit > 10_000_000:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10
    csv.field_size_limit(10_000_000)


_raise_csv_field_limit()

def _file_read_cache():
    """Import the decrypted file cache lazily to avoid secure_storage <-> cache startup cycles."""
    import importlib

    return importlib.import_module("money_manager.cache.file_read_cache")


def _json_object_cache():
    """Import parsed JSON cache lazily to avoid startup cycles."""
    import importlib

    return importlib.import_module("money_manager.cache.json_read_cache")


def read_json_secure(logical_name_or_path: str | os.PathLike[str], default: Any = None, user_id: str | None = None) -> Any:
    path, logical_name, resolved_user_id = _resolve(logical_name_or_path, user_id=user_id)
    try:
        if not path.exists():
            return default
        json_cache = _json_object_cache()
        cached = json_cache.get(path, user_id=resolved_user_id)
        if cached is not json_cache.sentinel():
            return cached
        raw = _read_bytes(path, logical_name=logical_name, user_id=resolved_user_id)
        if not raw:
            return default
        payload = json.loads(raw.decode("utf-8-sig"))
        json_cache.set_value(path, payload, user_id=resolved_user_id)
        return payload
    except Exception:
        return default


def write_json_secure(logical_name_or_path: str | os.PathLike[str], payload: Any, user_id: str | None = None) -> None:
    path, logical_name, resolved_user_id = _resolve(logical_name_or_path, user_id=user_id)
    raw = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
    try:
        _json_object_cache().invalidate_path(path, user_id=resolved_user_id)
    except Exception:
        pass
    _write_bytes(path, raw, logical_name=logical_name, user_id=resolved_user_id, content_type="application/json")
    try:
        _json_object_cache().set_value(path, payload, user_id=resolved_user_id)
    except Exception:
        pass
    _notify_cache_changed(path=path, logical_name=logical_name, user_id=resolved_user_id)

def secure_read_text(user_id: str | None, path: str | os.PathLike[str], encoding: str = "utf-8-sig") -> str:
    target, logical_name, resolved_user_id = _resolve(path, user_id=user_id)
    if not target.exists():
        raise FileNotFoundError(str(target))
    return _read_bytes(target, logical_name=logical_name, user_id=resolved_user_id).decode(encoding)


def secure_write_text(user_id: str | None, path: str | os.PathLike[str], text: str, encoding: str = "utf-8") -> None:
    target, logical_name, resolved_user_id = _resolve(path, user_id=user_id)
    _write_bytes(target, str(text or "").encode(encoding), logical_name=logical_name, user_id=resolved_user_id, content_type="text/plain")
    _notify_cache_changed(path=target, logical_name=logical_name, user_id=resolved_user_id)


def secure_read_bytes(user_id: str | None, path: str | os.PathLike[str]) -> bytes:
    return read_binary_secure(path, user_id=user_id)


def secure_write_bytes(user_id: str | None, path: str | os.PathLike[str], data: bytes) -> None:
    write_binary_secure(path, data, user_id=user_id)


def secure_read_json(user_id: str | None, path: str | os.PathLike[str], default: Any = None) -> Any:
    return read_json_secure(path, default=default, user_id=user_id)


def secure_write_json(user_id: str | None, path: str | os.PathLike[str], payload: Any) -> None:
    write_json_secure(path, payload, user_id=user_id)


def secure_read_csv(user_id: str | None, path: str | os.PathLike[str], fieldnames: list[str] | None = None, **kwargs) -> Any:
    fieldnames = list(fieldnames or kwargs.pop("fieldnames", []) or [])
    if not fieldnames:
        import pandas as pd
        raw = secure_read_text(user_id, path)
        return pd.read_csv(StringIO(raw), **kwargs)
    return read_csv_secure(path, fieldnames, user_id=user_id)


def secure_write_csv(user_id: str | None, path: str | os.PathLike[str], data: Any, fieldnames: list[str] | None = None, **kwargs) -> None:
    if hasattr(data, "to_csv"):
        target, logical_name, resolved_user_id = _resolve(path, user_id=user_id)
        text = data.to_csv(index=kwargs.pop("index", False), **kwargs)
        _write_bytes(target, text.encode("utf-8"), logical_name=logical_name, user_id=resolved_user_id, content_type="text/csv")
        _notify_cache_changed(path=target, logical_name=logical_name, user_id=resolved_user_id)
        return
    write_csv_secure(path, list(fieldnames or []), data, user_id=user_id)


def secure_save_upload(user_id: str | None, path: str | os.PathLike[str], uploaded_file: Any) -> None:
    data = uploaded_file.read()
    write_binary_secure(path, data, user_id=user_id, original_filename=getattr(uploaded_file, "filename", ""), content_type=getattr(uploaded_file, "mimetype", "") or "application/octet-stream")


def secure_delete(user_id: str | None, path: str | os.PathLike[str]) -> None:
    target, logical_name, resolved_user_id = _resolve(path, user_id=user_id)
    try:
        target.unlink(missing_ok=True)
        _file_read_cache().invalidate_path(target, user_id=resolved_user_id)
        try:
            _json_object_cache().invalidate_path(target, user_id=resolved_user_id)
        except Exception:
            pass
    finally:
        _notify_cache_changed(path=target, logical_name=logical_name, user_id=resolved_user_id)


def secure_exists(user_id: str | None, path: str | os.PathLike[str]) -> bool:
    target, _logical_name, _resolved_user_id = _resolve(path, user_id=user_id)
    return target.exists()


def read_csv_secure(logical_name_or_path: str | os.PathLike[str], fieldnames: list[str], user_id: str | None = None) -> list[dict[str, str]]:
    """Read a protected CSV with at most one decrypt/read pass.

    Older code called ``ensure_csv_secure()`` before every read.  With encrypted
    storage this decrypted the whole CSV once for schema validation and then
    decrypted it again for the actual read.  This function now performs the
    cheap missing-file check first, reads once, and only rewrites when headers
    really need repair.
    """
    path, logical_name, resolved_user_id = _resolve(logical_name_or_path, user_id=user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.stat().st_size == 0:
        output = StringIO()
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        _write_bytes(path, output.getvalue().encode("utf-8"), logical_name=logical_name, user_id=resolved_user_id, content_type="text/csv")
        return []

    raw = _read_bytes(path, logical_name=logical_name, user_id=resolved_user_id)
    text = raw.decode("utf-8-sig") if raw else ""
    if not text.strip():
        output = StringIO()
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        _write_bytes(path, output.getvalue().encode("utf-8"), logical_name=logical_name, user_id=resolved_user_id, content_type="text/csv")
        return []

    reader = csv.DictReader(StringIO(text))
    existing_fields = list(reader.fieldnames or [])
    rows = [dict(row) for row in reader]
    if not existing_fields:
        output = StringIO()
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        _write_bytes(path, output.getvalue().encode("utf-8"), logical_name=logical_name, user_id=resolved_user_id, content_type="text/csv")
        return []

    missing = [field for field in fieldnames if field not in existing_fields]
    if missing:
        final_fields = [*fieldnames, *[field for field in existing_fields if field not in fieldnames]]
        for row in rows:
            for field in missing:
                row[field] = ""
        write_csv_secure(path, final_fields, rows, user_id=resolved_user_id)

    return rows


def write_csv_secure(logical_name_or_path: str | os.PathLike[str], fieldnames: list[str], rows: Iterable[dict[str, Any]], user_id: str | None = None) -> None:
    path, logical_name, resolved_user_id = _resolve(logical_name_or_path, user_id=user_id)
    existing_headers = _csv_headers_from_path(path, fieldnames, logical_name=logical_name, user_id=resolved_user_id)
    headers = [*fieldnames, *[header for header in existing_headers if header not in fieldnames]]
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: (row.get(field, "") if isinstance(row, dict) else "") for field in headers})
    _write_bytes(path, output.getvalue().encode("utf-8"), logical_name=logical_name, user_id=resolved_user_id, content_type="text/csv")
    _notify_cache_changed(path=path, logical_name=logical_name, user_id=resolved_user_id)


def append_csv_row_secure(logical_name_or_path: str | os.PathLike[str], fieldnames: list[str], row: dict[str, Any], user_id: str | None = None) -> None:
    rows = read_csv_secure(logical_name_or_path, fieldnames, user_id=user_id)
    rows.append(dict(row or {}))
    write_csv_secure(logical_name_or_path, fieldnames, rows, user_id=user_id)


def ensure_csv_secure(logical_name_or_path: str | os.PathLike[str], fieldnames: list[str], user_id: str | None = None, *, preserve_unknown_columns: bool = True) -> tuple[bool, list[str]]:
    path, logical_name, resolved_user_id = _resolve(logical_name_or_path, user_id=user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.stat().st_size == 0:
        output = StringIO()
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        _write_bytes(path, output.getvalue().encode("utf-8"), logical_name=logical_name, user_id=resolved_user_id, content_type="text/csv")
        return True, []

    raw = _read_bytes(path, logical_name=logical_name, user_id=resolved_user_id)
    text = raw.decode("utf-8-sig") if raw else ""
    reader = csv.DictReader(StringIO(text))
    existing_fields = list(reader.fieldnames or [])
    rows = list(reader)
    if not existing_fields:
        output = StringIO()
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        _write_bytes(path, output.getvalue().encode("utf-8"), logical_name=logical_name, user_id=resolved_user_id, content_type="text/csv")
        return True, []
    missing = [field for field in fieldnames if field not in existing_fields]
    if not missing:
        return False, []
    final_fields = list(fieldnames)
    if preserve_unknown_columns:
        final_fields.extend(field for field in existing_fields if field not in final_fields)
    for row in rows:
        for field in missing:
            row[field] = ""
    write_csv_secure(path, final_fields, rows, user_id=resolved_user_id)
    return False, missing


def read_binary_secure(path: str | os.PathLike[str], user_id: str | None = None) -> bytes:
    target, logical_name, resolved_user_id = _resolve(path, user_id=user_id)
    if not target.exists():
        raise FileNotFoundError(str(target))
    return _read_bytes(target, logical_name=logical_name, user_id=resolved_user_id)


def write_binary_secure(path: str | os.PathLike[str], bytes_data: bytes, user_id: str | None = None, *, original_filename: str = "", content_type: str = "") -> None:
    target, logical_name, resolved_user_id = _resolve(path, user_id=user_id)
    _write_bytes(
        target,
        bytes(bytes_data or b""),
        logical_name=logical_name,
        user_id=resolved_user_id,
        content_type=content_type or mimetypes.guess_type(target.name)[0] or "application/octet-stream",
        original_filename=original_filename or target.name,
    )


def encrypt_path_if_needed(path: str | os.PathLike[str], user_id: str | None = None, *, logical_name: str = "", content_type: str = "", original_filename: str = "") -> bool:
    target = Path(path)
    resolved_user_id = user_id or _infer_user_id(target) or get_current_user_id()
    if not target.exists() or not target.is_file():
        return False
    if not _should_encrypt(target, logical_name=logical_name, user_id=resolved_user_id):
        return False
    raw = target.read_bytes()
    if is_encrypted_bytes(raw):
        return False
    dek = require_dek(resolved_user_id)
    encrypted = encrypt_bytes(
        raw,
        dek,
        content_type=content_type or mimetypes.guess_type(target.name)[0] or "application/octet-stream",
        original_logical_name=logical_name or _relative_logical_name(target, resolved_user_id) or target.name,
        original_filename=original_filename or target.name,
    )
    _atomic_write_bytes(target, encrypted)
    return True


def is_path_encrypted(path: str | os.PathLike[str]) -> bool:
    return is_file_encrypted(path)


def _read_bytes(path: Path, *, logical_name: str = "", user_id: str | None = None) -> bytes:
    resolved_user_id = user_id or _infer_user_id(path) or get_current_user_id()
    cache = _file_read_cache()
    cached = cache.get(path, user_id=resolved_user_id)
    if cached is not cache.sentinel():
        return bytes(cached)

    raw = path.read_bytes()
    if is_encrypted_bytes(raw):
        dek = require_dek(resolved_user_id)
        decoded = decrypt_bytes(raw, dek)
    else:
        decoded = raw
    cache.set_value(path, decoded, user_id=resolved_user_id)
    return decoded


def _write_bytes(path: Path, raw: bytes, *, logical_name: str = "", user_id: str | None = None, content_type: str = "application/octet-stream", original_filename: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    resolved_user_id = user_id or _infer_user_id(path) or get_current_user_id()
    plaintext = bytes(raw or b"")
    should_encrypt = _should_encrypt(path, logical_name=logical_name, user_id=resolved_user_id)

    cache = _file_read_cache()

    try:
        if path.exists() and path.is_file():
            existing_payload = path.read_bytes()
            existing_encrypted = is_encrypted_bytes(existing_payload)

            if existing_encrypted:
                dek = require_dek(resolved_user_id)
                existing_plaintext = decrypt_bytes(existing_payload, dek)
            else:
                existing_plaintext = existing_payload

            encryption_state_already_correct = (
                (should_encrypt and existing_encrypted)
                or ((not should_encrypt) and (not existing_encrypted))
            )

            if existing_plaintext == plaintext and encryption_state_already_correct:
                cache.set_value(path, plaintext, user_id=resolved_user_id)
                return
    except Exception:
        pass

    payload = plaintext
    if should_encrypt:
        dek = require_dek(resolved_user_id)
        payload = encrypt_bytes(
            plaintext,
            dek,
            content_type=content_type,
            original_logical_name=logical_name or _relative_logical_name(path, resolved_user_id) or path.name,
            original_filename=original_filename or path.name,
        )

    cache.invalidate_path(path, user_id=resolved_user_id)
    try:
        _json_object_cache().invalidate_path(path, user_id=resolved_user_id)
    except Exception:
        pass

    _atomic_write_bytes(path, payload)
    cache.set_value(path, plaintext, user_id=resolved_user_id)


def _should_encrypt(path: Path, *, logical_name: str = "", user_id: str | None = None) -> bool:
    if not user_id or not is_encryption_enabled(user_id):
        return False
    definition = None
    if logical_name:
        definition = definition_by_name(logical_name) or definition_for_filename(logical_name)
    relative = _relative_logical_name(path, user_id)
    if definition is None and relative:
        definition = definition_for_filename(relative)
    if definition is not None:
        if getattr(definition, "encrypted_by_default", False):
            return True
        if str(getattr(definition, "encryption_policy", "none")) == "required":
            return True
    return is_sensitive_user_relative_path(relative or logical_name or path.name)


def _is_sensitive_user_path(path: Path, *, logical_name: str = "", user_id: str | None = None) -> bool:
    definition = definition_by_name(logical_name) or definition_for_filename(logical_name) if logical_name else None
    relative = _relative_logical_name(path, user_id) if user_id else ""
    if definition is None and relative:
        definition = definition_for_filename(relative)
    if definition is not None:
        return bool(getattr(definition, "encrypted_by_default", False)) or str(getattr(definition, "encryption_policy", "none")) == "required"
    return is_sensitive_user_relative_path(relative or logical_name or path.name)


def _resolve(logical_name_or_path: str | os.PathLike[str], user_id: str | None = None) -> tuple[Path, str, str | None]:
    value = os.fspath(logical_name_or_path)
    definition = definition_by_name(value) or definition_for_filename(value)
    if definition is not None:
        from money_manager.storage.data_file_service import resolve_definition_path
        if definition.scope == "user":
            uid = user_id or get_current_user_id()
            if not uid:
                raise RuntimeError(f"User id is required for user-scoped data file {definition.name}.")
            resolved_user_id = normalize_user_id(uid)
        else:
            resolved_user_id = user_id
        return resolve_definition_path(definition, user_id=resolved_user_id), definition.name, resolved_user_id
    path = Path(logical_name_or_path)
    resolved_user_id = user_id or _infer_user_id(path) or get_current_user_id()
    return path, _relative_logical_name(path, resolved_user_id) or path.name, normalize_user_id(resolved_user_id) if resolved_user_id else None


def _infer_user_id(path: Path) -> str | None:
    try:
        resolved = path.resolve()
        root = USERS_DIR.resolve()
        relative = resolved.relative_to(root)
        if relative.parts:
            return normalize_user_id(relative.parts[0])
    except Exception:
        return None
    return None


def _relative_logical_name(path: Path, user_id: str | None) -> str:
    if not user_id:
        return ""
    try:
        user_root = (USERS_DIR / normalize_user_id(user_id)).resolve()
        return path.resolve().relative_to(user_root).as_posix()
    except Exception:
        return ""


def _csv_headers_from_path(path: Path, fallback: list[str], *, logical_name: str = "", user_id: str | None = None) -> list[str]:
    try:
        if not path.exists():
            return fallback
        raw = _read_bytes(path, logical_name=logical_name, user_id=user_id)
        reader = csv.reader(StringIO(raw.decode("utf-8-sig")))
        headers = next(reader, [])
        return headers or fallback
    except Exception:
        return fallback


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("wb", delete=False, dir=str(path.parent), prefix=f".{path.stem}.", suffix=".tmp") as tmp:
        tmp.write(payload)
        temp_name = tmp.name
    Path(temp_name).replace(path)


def _notify_cache_changed(path: Path | None = None, logical_name: str = "", user_id: str | None = None) -> None:
    try:
        from money_manager.services.cache_service import notify_path_changed, notify_data_changed
        if path is not None:
            notify_path_changed(str(path), user_id=user_id)
        elif logical_name:
            notify_data_changed(tags=[logical_name], user_id=user_id)
        else:
            notify_data_changed(user_id=user_id)
    except Exception:
        pass
