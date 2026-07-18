from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Mapping

from money_manager.config.user_paths import get_user_data_dir
from money_manager.security.secure_storage import read_json_secure, write_json_secure, read_binary_secure, write_binary_secure

DETAILS_FILE = "payable_details.json"
ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "webp", "csv", "xlsx", "xls", "ods", "txt", "doc", "docx", "odt"}
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def _store_path() -> Path:
    return get_user_data_dir() / DETAILS_FILE


def _load() -> dict[str, Any]:
    payload = read_json_secure(_store_path(), default={})
    return payload if isinstance(payload, dict) else {}


def _write(payload: dict[str, Any]) -> None:
    write_json_secure(_store_path(), payload)


def details_for_payable(payable_id: Any) -> dict[str, Any]:
    row = dict(_load().get(str(payable_id), {}) or {})
    row.setdefault("items", [])
    row.setdefault("files", [])
    row["items_total"] = round(sum(float(item.get("quantity", 0) or 0) * float(item.get("unit_value", 0) or 0) for item in row["items"]), 2)
    return row


def save_items_from_form(payable_id: Any, form: Mapping[str, Any]) -> None:
    names = form.getlist("item_name") if hasattr(form, "getlist") else []
    quantities = form.getlist("item_quantity") if hasattr(form, "getlist") else []
    values = form.getlist("item_unit_value") if hasattr(form, "getlist") else []
    items = []
    for index, name in enumerate(names):
        name = str(name or "").strip()
        if not name:
            continue
        try:
            quantity = max(0.0, float(quantities[index] if index < len(quantities) else 0))
            unit_value = max(0.0, float(values[index] if index < len(values) else 0))
        except (TypeError, ValueError):
            continue
        items.append({"name": name, "quantity": quantity, "unit_value": unit_value})
    payload = _load()
    entry = dict(payload.get(str(payable_id), {}) or {})
    entry["items"] = items
    entry.setdefault("files", [])
    payload[str(payable_id)] = entry
    _write(payload)


def save_uploaded_files(payable_id: Any, uploads) -> dict[str, Any]:
    payable_key = str(payable_id or "").strip()
    result: dict[str, Any] = {"saved": [], "errors": []}
    if not payable_key:
        result["errors"].append("The payable could not be identified.")
        return result

    payload = _load()
    entry = dict(payload.get(payable_key, {}) or {})
    files = list(entry.get("files", []) or [])
    upload_dir = get_user_data_dir() / "payable_uploads" / payable_key
    upload_dir.mkdir(parents=True, exist_ok=True)

    for upload in list(uploads or []):
        filename = Path(str(getattr(upload, "filename", "") or "")).name
        if not filename:
            continue
        ext = filename.rsplit(".", 1)[-1].casefold() if "." in filename else ""
        if ext not in ALLOWED_EXTENSIONS:
            result["errors"].append(f"{filename}: unsupported file type.")
            continue
        data = upload.read()
        if not data:
            result["errors"].append(f"{filename}: the selected file is empty.")
            continue
        if len(data) > MAX_UPLOAD_BYTES:
            result["errors"].append(f"{filename}: file is larger than 25 MB.")
            continue
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("._") or f"attachment.{ext}"
        candidate = safe
        counter = 2
        while (upload_dir / candidate).exists():
            stem, suffix = Path(safe).stem, Path(safe).suffix
            candidate = f"{stem}_{counter}{suffix}"
            counter += 1
        try:
            write_binary_secure(
                upload_dir / candidate,
                data,
                original_filename=filename,
                content_type=getattr(upload, "mimetype", "") or "application/octet-stream",
            )
        except Exception as exc:
            result["errors"].append(f"{filename}: upload failed ({exc}).")
            continue
        files.append({
            "stored_name": candidate,
            "display_name": filename,
            "mime_type": getattr(upload, "mimetype", "") or "application/octet-stream",
            "size_bytes": len(data),
        })
        result["saved"].append(candidate)

    entry["files"] = files
    entry.setdefault("items", [])
    payload[payable_key] = entry
    _write(payload)
    return result


def read_payable_file(payable_id: Any, stored_name: str) -> tuple[bytes, dict[str, str]] | None:
    details = details_for_payable(payable_id)
    match = next((row for row in details["files"] if row.get("stored_name") == stored_name), None)
    if not match:
        return None
    path = get_user_data_dir() / "payable_uploads" / str(payable_id) / Path(stored_name).name
    if not path.exists():
        return None
    return read_binary_secure(path), match
