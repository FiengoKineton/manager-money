from __future__ import annotations

import uuid
from typing import Any, Mapping

from money_manager.config.user_defaults import DEFAULT_CONTACTS
from money_manager.services._user_config import load_user_config, save_user_config, safe_update_fields, utc_now

CONTACTS_FILE = "contacts.json"
CONTACT_FIELDS = {
    "name",
    "surname_company",
    "relationship",
    "iban",
    "bic_swift",
    "bank_name",
    "notes",
    "is_archived",
}


def load_contacts_config(user_id: str | None = None) -> dict[str, Any]:
    return _normalize_contacts_config(load_user_config(CONTACTS_FILE, user_id=user_id))


def save_contacts_config(config: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    return save_user_config(CONTACTS_FILE, _normalize_contacts_config(config), user_id=user_id)


def list_contacts(user_id: str | None = None, *, include_archived: bool = False) -> list[dict[str, Any]]:
    contacts = load_contacts_config(user_id=user_id).get("contacts", [])
    if include_archived:
        return contacts
    return [contact for contact in contacts if not bool(contact.get("is_archived"))]


def get_contact(contact_id: str, user_id: str | None = None) -> dict[str, Any] | None:
    wanted = _clean_id(contact_id)
    for contact in load_contacts_config(user_id=user_id).get("contacts", []):
        if contact.get("id") == wanted:
            return contact
    return None


def add_contact(data: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    config = load_contacts_config(user_id=user_id)
    contact = _normalize_contact(data)
    contact["id"] = _new_contact_id(config.get("contacts", []))
    now = utc_now()
    contact["created_at"] = now
    contact["updated_at"] = now
    config["contacts"].append(contact)
    save_contacts_config(config, user_id=user_id)
    return contact


def update_contact(contact_id: str, updates: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    config = load_contacts_config(user_id=user_id)
    wanted = _clean_id(contact_id)
    for index, contact in enumerate(config.get("contacts", [])):
        if contact.get("id") == wanted:
            updated = safe_update_fields(contact, updates, allowed_fields=CONTACT_FIELDS)
            updated = _normalize_contact(updated)
            updated["id"] = wanted
            updated["created_at"] = contact.get("created_at") or utc_now()
            updated["updated_at"] = utc_now()
            config["contacts"][index] = updated
            save_contacts_config(config, user_id=user_id)
            return updated
    raise ValueError("Contact not found.")


def archive_contact(contact_id: str, user_id: str | None = None) -> dict[str, Any]:
    return update_contact(contact_id, {"is_archived": True}, user_id=user_id)


def restore_contact(contact_id: str, user_id: str | None = None) -> dict[str, Any]:
    return update_contact(contact_id, {"is_archived": False}, user_id=user_id)


def delete_contact(contact_id: str, user_id: str | None = None, *, hard_delete: bool = False) -> dict[str, Any] | None:
    if not hard_delete:
        return archive_contact(contact_id, user_id=user_id)
    config = load_contacts_config(user_id=user_id)
    wanted = _clean_id(contact_id)
    before = len(config.get("contacts", []))
    config["contacts"] = [contact for contact in config.get("contacts", []) if contact.get("id") != wanted]
    if len(config["contacts"]) == before:
        raise ValueError("Contact not found.")
    save_contacts_config(config, user_id=user_id)
    return None


def ensure_contacts_config(user_id: str | None = None) -> dict[str, Any]:
    return load_contacts_config(user_id=user_id)


def _normalize_contacts_config(config: Mapping[str, Any]) -> dict[str, Any]:
    clean = dict(DEFAULT_CONTACTS)
    incoming = dict(config or {})
    clean["schema_version"] = incoming.get("schema_version") or DEFAULT_CONTACTS["schema_version"]
    raw_contacts = incoming.get("contacts", [])
    contacts = raw_contacts if isinstance(raw_contacts, list) else []
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for contact in contacts:
        item = _normalize_contact(contact)
        if not item["id"] or item["id"] in seen:
            item["id"] = _new_contact_id(normalized)
        seen.add(item["id"])
        normalized.append(item)
    clean["contacts"] = normalized
    for key, value in incoming.items():
        if key not in clean:
            clean[key] = value
    return clean


def _normalize_contact(data: Mapping[str, Any] | None) -> dict[str, Any]:
    data = dict(data or {})
    return {
        "id": _clean_id(data.get("id")),
        "name": _clean_text(data.get("name")),
        "surname_company": _clean_text(data.get("surname_company") or data.get("surname") or data.get("company")),
        "relationship": _clean_text(data.get("relationship")),
        "iban": _clean_text(data.get("iban")),
        "bic_swift": _clean_text(data.get("bic_swift") or data.get("bic") or data.get("swift")),
        "bank_name": _clean_text(data.get("bank_name")),
        "notes": _clean_text(data.get("notes")),
        "is_archived": _as_bool(data.get("is_archived", False), default=False),
        "created_at": _clean_text(data.get("created_at")),
        "updated_at": _clean_text(data.get("updated_at")),
    }


def _new_contact_id(existing_contacts: list[Mapping[str, Any]]) -> str:
    existing = {_clean_id(contact.get("id")) for contact in existing_contacts}
    while True:
        candidate = f"contact_{uuid.uuid4().hex[:12]}"
        if candidate not in existing:
            return candidate


def _clean_id(value: Any) -> str:
    text = str(value or "").strip().lower()
    return "".join(char for char in text if char.isalnum() or char in {"_", "-"})[:80]


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
