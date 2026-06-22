from __future__ import annotations

import re
from typing import Any, Mapping

from money_manager.config.user_defaults import DEFAULT_DOCUMENT_TYPES
from money_manager.services._user_config import config_path, load_user_config, save_user_config, utc_now

DOCUMENT_TYPES_FILE = "document_types.json"
DOCUMENT_TYPE_FIELDS = {
    "name",
    "description",
    "is_active",
    "display_order",
}


def load_document_types_config(user_id: str | None = None) -> dict[str, Any]:
    raw = load_user_config(DOCUMENT_TYPES_FILE, user_id=user_id, repair=False)
    config = _normalize_document_types_config(raw)
    if raw != config or not config_path(DOCUMENT_TYPES_FILE, user_id=user_id).exists():
        save_user_config(DOCUMENT_TYPES_FILE, config, user_id=user_id)
    return config


def save_document_types_config(config: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    return save_user_config(DOCUMENT_TYPES_FILE, _normalize_document_types_config(config), user_id=user_id)


def active_document_types(user_id: str | None = None) -> list[dict[str, Any]]:
    return [item for item in all_document_types(user_id=user_id) if item.get("is_active") is True]


def all_document_types(user_id: str | None = None) -> list[dict[str, Any]]:
    return sorted(
        load_document_types_config(user_id=user_id).get("types", []),
        key=lambda item: (int(item.get("display_order") or 0), str(item.get("name") or "").casefold()),
    )


def get_document_type(type_id: str, user_id: str | None = None) -> dict[str, Any] | None:
    wanted = _slugify(type_id)
    for item in load_document_types_config(user_id=user_id).get("types", []):
        if item.get("id") == wanted:
            return item
    return None


def add_document_type(
    name: str,
    description: str = "",
    user_id: str | None = None,
    *,
    display_order: int | None = None,
    type_id: str | None = None,
) -> dict[str, Any]:
    clean_name = _clean_name(name)
    if not clean_name:
        raise ValueError("Document type name is required.")
    config = load_document_types_config(user_id=user_id)
    new_id = _slugify(type_id or clean_name)
    if not new_id:
        raise ValueError("Document type id is invalid.")
    _assert_no_duplicate_active(config, candidate_id=new_id, candidate_name=clean_name)
    if any(item.get("id") == new_id for item in config.get("types", [])):
        new_id = _unique_id(new_id, config.get("types", []))
    item = {
        "id": new_id,
        "name": clean_name,
        "description": _clean_text(description),
        "is_default": False,
        "is_active": True,
        "display_order": int(display_order if display_order is not None else _next_display_order(config.get("types", []))),
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    config["types"].append(item)
    save_document_types_config(config, user_id=user_id)
    return item


def edit_document_type(type_id: str, updates: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    wanted = _slugify(type_id)
    config = load_document_types_config(user_id=user_id)
    for index, item in enumerate(config.get("types", [])):
        if item.get("id") != wanted:
            continue
        updated = dict(item)
        for field in DOCUMENT_TYPE_FIELDS:
            if field not in updates:
                continue
            value = updates[field]
            if field == "name":
                updated["name"] = _clean_name(value)
            elif field == "description":
                updated["description"] = _clean_text(value)
            elif field == "is_active":
                updated["is_active"] = _as_bool(value, default=True)
            elif field == "display_order":
                try:
                    updated["display_order"] = int(value)
                except (TypeError, ValueError):
                    pass
        if not updated.get("name"):
            raise ValueError("Document type name is required.")
        if updated.get("is_active") is True:
            _assert_no_duplicate_active(
                config,
                candidate_id=updated["id"],
                candidate_name=updated["name"],
                exclude_id=wanted,
            )
        updated["updated_at"] = utc_now()
        config["types"][index] = _normalize_document_type(updated)
        save_document_types_config(config, user_id=user_id)
        return config["types"][index]
    raise ValueError("Document type not found.")


def archive_document_type(type_id: str, user_id: str | None = None) -> dict[str, Any]:
    return edit_document_type(type_id, {"is_active": False}, user_id=user_id)


def restore_document_type(type_id: str, user_id: str | None = None) -> dict[str, Any]:
    return edit_document_type(type_id, {"is_active": True}, user_id=user_id)


def ensure_document_types_config(user_id: str | None = None) -> dict[str, Any]:
    return load_document_types_config(user_id=user_id)


def document_type_choices(user_id: str | None = None) -> list[tuple[str, str]]:
    return [(item["id"], item["name"]) for item in active_document_types(user_id=user_id)]


def document_type_name(type_id: str, user_id: str | None = None) -> str:
    item = get_document_type(type_id, user_id=user_id)
    return str(item.get("name") or type_id) if item else str(type_id or "")


def _normalize_document_types_config(config: Mapping[str, Any] | None) -> dict[str, Any]:
    incoming = dict(config or {}) if isinstance(config, Mapping) else {}
    clean = {
        "schema_version": incoming.get("schema_version") or DEFAULT_DOCUMENT_TYPES["schema_version"],
        "types": [],
    }

    source_types = incoming.get("types", [])
    if not isinstance(source_types, list):
        source_types = []

    by_id: dict[str, dict[str, Any]] = {}
    for raw in source_types:
        item = _normalize_document_type(raw)
        if not item.get("id"):
            item["id"] = _unique_id(_slugify(item.get("name")) or "document_type", list(by_id.values()))
        if item["id"] in by_id:
            item["id"] = _unique_id(item["id"], list(by_id.values()))
        by_id[item["id"]] = item

    # Merge missing built-in defaults without overwriting user-edited values.
    for default_item in DEFAULT_DOCUMENT_TYPES["types"]:
        default_normalized = _normalize_document_type(default_item)
        existing = by_id.get(default_normalized["id"])
        if existing:
            merged = dict(default_normalized)
            merged.update(existing)
            merged["is_default"] = True
            by_id[default_normalized["id"]] = _normalize_document_type(merged)
        else:
            by_id[default_normalized["id"]] = default_normalized

    clean["types"] = _dedupe_active_types(list(by_id.values()))
    for key, value in incoming.items():
        if key not in clean:
            clean[key] = value
    return clean


def _normalize_document_type(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    raw = dict(raw or {}) if isinstance(raw, Mapping) else {}
    type_id = _slugify(raw.get("id") or raw.get("name"))
    display_order = raw.get("display_order", 100)
    try:
        display_order = int(display_order)
    except (TypeError, ValueError):
        display_order = 100
    return {
        "id": type_id,
        "name": _clean_name(raw.get("name") or type_id.replace("_", " ").title()),
        "description": _clean_text(raw.get("description")),
        "is_default": _as_bool(raw.get("is_default", False), default=False),
        "is_active": _as_bool(raw.get("is_active", True), default=True),
        "display_order": display_order,
        **({"created_at": _clean_text(raw.get("created_at"))} if raw.get("created_at") else {}),
        **({"updated_at": _clean_text(raw.get("updated_at"))} if raw.get("updated_at") else {}),
    }


def _dedupe_active_types(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in sorted(items, key=lambda entry: (int(entry.get("display_order") or 0), str(entry.get("name") or "").casefold())):
        if item.get("is_active") is True:
            id_key = str(item.get("id") or "")
            name_key = str(item.get("name") or "").casefold()
            if id_key in seen_ids or name_key in seen_names:
                item = dict(item)
                item["is_active"] = False
                item["updated_at"] = item.get("updated_at") or utc_now()
            else:
                seen_ids.add(id_key)
                seen_names.add(name_key)
        result.append(item)
    return result


def _assert_no_duplicate_active(
    config: Mapping[str, Any],
    *,
    candidate_id: str,
    candidate_name: str,
    exclude_id: str | None = None,
) -> None:
    candidate_id = _slugify(candidate_id)
    candidate_name_key = _clean_name(candidate_name).casefold()
    exclude_id = _slugify(exclude_id)
    for item in config.get("types", []):
        if item.get("id") == exclude_id:
            continue
        if item.get("is_active") is not True:
            continue
        if item.get("id") == candidate_id:
            raise ValueError("An active document type with this id already exists.")
        if str(item.get("name") or "").casefold() == candidate_name_key:
            raise ValueError("An active document type with this name already exists.")


def _unique_id(base_id: str, items: list[Mapping[str, Any]]) -> str:
    existing = {str(item.get("id") or "") for item in items}
    candidate = _slugify(base_id) or "document_type"
    if candidate not in existing:
        return candidate
    for index in range(2, 1000):
        option = f"{candidate}_{index}"
        if option not in existing:
            return option
    raise ValueError("Could not create a unique document type id.")


def _next_display_order(items: list[Mapping[str, Any]]) -> int:
    orders = []
    for item in items:
        try:
            orders.append(int(item.get("display_order") or 0))
        except (TypeError, ValueError):
            continue
    return (max(orders) if orders else 0) + 10


def _slugify(value: Any) -> str:
    text = str(value or "").strip().casefold()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_")[:80]


def _clean_name(value: Any) -> str:
    return " ".join(str(value or "").strip().split())[:120]


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _as_bool(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().casefold()
        if text in {"1", "true", "yes", "y", "on"}:
            return True
        if text in {"0", "false", "no", "n", "off"}:
            return False
    if value is None:
        return default
    return bool(value)
