from __future__ import annotations

import uuid
from typing import Any, Mapping

from money_manager.config.user_defaults import DEFAULT_CONTACTS
from money_manager.services._user_config import load_user_config, save_user_config, safe_update_fields, utc_now
from money_manager.utils.privacy import mask_iban

CONTACTS_FILE = "contacts.json"
VALID_CONTACT_TYPES = {"person", "company"}
CONTACT_FIELDS = {
    "type",
    "first_name",
    "last_name",
    "company_name",
    "display_name",
    "relationship",
    "iban",
    "bic_swift",
    "bank_name",
    "email",
    "phone",
    "vat_number",
    "fiscal_code",
    "pec_email",
    "sdi_code",
    "registered_address",
    "city",
    "province",
    "postal_code",
    "country",
    "notes",
    "is_archived",
}
SEARCH_FIELDS = ("display_name", "first_name", "last_name", "company_name", "relationship", "iban", "vat_number", "fiscal_code", "pec_email", "sdi_code")


def load_contacts_config(user_id: str | None = None) -> dict[str, Any]:
    raw = load_user_config(CONTACTS_FILE, user_id=user_id)
    normalized = _normalize_contacts_config(raw)
    if normalized != raw:
        try:
            save_user_config(CONTACTS_FILE, normalized, user_id=user_id)
        except RuntimeError:
            pass
    return normalized


def save_contacts_config(config: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    return save_user_config(CONTACTS_FILE, _normalize_contacts_config(config), user_id=user_id)


def list_contacts(user_id: str | None = None, *, include_archived: bool = False) -> list[dict[str, Any]]:
    contacts = load_contacts_config(user_id=user_id).get("contacts", [])
    if not include_archived:
        contacts = [contact for contact in contacts if not bool(contact.get("is_archived"))]
    return sorted(contacts, key=_contact_sort_key)


def search_contacts(query: str | None = None, user_id: str | None = None, *, include_archived: bool = False) -> list[dict[str, Any]]:
    contacts = list_contacts(user_id=user_id, include_archived=include_archived)
    needle = _search_text(query)
    if not needle:
        return contacts
    return [contact for contact in contacts if _contact_matches(contact, needle)]


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
    """Archive by default so historical transaction references remain safe."""
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


def duplicate_warnings(data: Mapping[str, Any], user_id: str | None = None, *, exclude_id: str | None = None) -> list[str]:
    """Return soft duplicate warning codes. The caller may still save the contact."""
    candidate = _normalize_contact(data)
    display_key = _dedupe_text(candidate.get("display_name"))
    iban_key = _canonical_iban(candidate.get("iban"))
    excluded = _clean_id(exclude_id)
    warnings: list[str] = []
    for contact in list_contacts(user_id=user_id, include_archived=True):
        if excluded and contact.get("id") == excluded:
            continue
        if display_key and _dedupe_text(contact.get("display_name")) == display_key and "duplicate_name" not in warnings:
            warnings.append("duplicate_name")
        if iban_key and _canonical_iban(contact.get("iban")) == iban_key and "duplicate_iban" not in warnings:
            warnings.append("duplicate_iban")
    return warnings


def prepare_contact_for_form(contact: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return _normalize_contact(contact)


def contact_view(contact: Mapping[str, Any], *, show_sensitive_data: bool = False) -> dict[str, Any]:
    item = _normalize_contact(contact)
    iban = str(item.get("iban") or "")
    item["iban_display"] = format_iban(iban)
    item["iban_list_value"] = format_iban(iban) if show_sensitive_data else mask_iban(iban)
    item["bic_swift_display"] = item.get("bic_swift") if show_sensitive_data else ("••••" if item.get("bic_swift") else "")
    item["bank_name_display"] = item.get("bank_name") if show_sensitive_data else ("••••" if item.get("bank_name") else "")
    item["has_bank_details"] = bool(iban or item.get("bic_swift") or item.get("bank_name"))
    return item


def contact_views(
    contacts: list[Mapping[str, Any]],
    *,
    show_sensitive_data: bool = False,
) -> list[dict[str, Any]]:
    return [contact_view(contact, show_sensitive_data=show_sensitive_data) for contact in contacts]


def contact_counts(user_id: str | None = None) -> dict[str, int]:
    contacts = list_contacts(user_id=user_id, include_archived=True)
    active = [contact for contact in contacts if not bool(contact.get("is_archived"))]
    archived = [contact for contact in contacts if bool(contact.get("is_archived"))]
    return {
        "total": len(contacts),
        "active": len(active),
        "archived": len(archived),
        "people": sum(1 for contact in active if contact.get("type") == "person"),
        "companies": sum(1 for contact in active if contact.get("type") == "company"),
    }


def ensure_contacts_config(user_id: str | None = None) -> dict[str, Any]:
    return load_contacts_config(user_id=user_id)


def format_iban(iban: str | None) -> str:
    canonical = _canonical_iban(iban)
    return " ".join(canonical[index : index + 4] for index in range(0, len(canonical), 4))


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
    clean["contacts"] = sorted(normalized, key=_contact_sort_key)
    for key, value in incoming.items():
        if key not in clean:
            clean[key] = value
    return clean


def _normalize_contact(data: Mapping[str, Any] | None) -> dict[str, Any]:
    data = dict(data or {})
    contact_type = _clean_text(data.get("type")).casefold()
    if contact_type not in VALID_CONTACT_TYPES:
        contact_type = "company" if data.get("company_name") and not data.get("first_name") else "person"

    first_name = _clean_text(data.get("first_name") or data.get("name"))
    last_name = _clean_text(data.get("last_name") or data.get("surname"))
    company_name = _clean_text(data.get("company_name") or data.get("company"))

    old_surname_company = _clean_text(data.get("surname_company"))
    if old_surname_company:
        if contact_type == "company" and not company_name:
            company_name = old_surname_company
        elif contact_type == "person" and not last_name:
            last_name = old_surname_company

    display_name = _clean_text(data.get("display_name"))
    if not display_name:
        if contact_type == "company":
            display_name = company_name or " ".join(part for part in [first_name, last_name] if part).strip()
        else:
            display_name = " ".join(part for part in [first_name, last_name] if part).strip() or company_name
    if not display_name:
        display_name = "Unnamed contact"

    return {
        "id": _clean_id(data.get("id")),
        "type": contact_type,
        "first_name": first_name,
        "last_name": last_name,
        "company_name": company_name,
        "display_name": display_name,
        "relationship": _clean_text(data.get("relationship")),
        "iban": _canonical_iban(data.get("iban")),
        "bic_swift": _clean_text(data.get("bic_swift") or data.get("bic") or data.get("swift")).upper(),
        "bank_name": _clean_text(data.get("bank_name")),
        "email": _clean_email(data.get("email")),
        "phone": _clean_text(data.get("phone")),
        "vat_number": _clean_vat(data.get("vat_number") or data.get("partita_iva") or data.get("piva")),
        "fiscal_code": _clean_fiscal_code(data.get("fiscal_code") or data.get("codice_fiscale")),
        "pec_email": _clean_email(data.get("pec_email") or data.get("pec")),
        "sdi_code": _clean_sdi(data.get("sdi_code") or data.get("codice_destinatario") or data.get("sdi")),
        "registered_address": _clean_text(data.get("registered_address") or data.get("address")),
        "city": _clean_text(data.get("city")),
        "province": _clean_text(data.get("province")).upper(),
        "postal_code": _clean_text(data.get("postal_code") or data.get("zip_code") or data.get("cap")),
        "country": _clean_text(data.get("country")) or ("Italy" if contact_type == "company" else ""),
        "notes": _clean_multiline(data.get("notes")),
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


def _contact_matches(contact: Mapping[str, Any], needle: str) -> bool:
    haystack = " ".join(_search_text(contact.get(field)) for field in SEARCH_FIELDS)
    return needle in haystack


def _contact_sort_key(contact: Mapping[str, Any]) -> tuple[int, str, str]:
    return (
        1 if bool(contact.get("is_archived")) else 0,
        _search_text(contact.get("display_name")),
        _clean_id(contact.get("id")),
    )


def _clean_id(value: Any) -> str:
    text = str(value or "").strip().lower()
    return "".join(char for char in text if char.isalnum() or char in {"_", "-"})[:80]


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _clean_multiline(value: Any) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [" ".join(line.strip().split()) for line in text.split("\n")]
    return "\n".join(line for line in lines if line).strip()


def _clean_email(value: Any) -> str:
    return _clean_text(value).lower()


def _canonical_iban(value: Any) -> str:
    return "".join(str(value or "").split()).upper()


def _dedupe_text(value: Any) -> str:
    return _search_text(value)


def _search_text(value: Any) -> str:
    return " ".join(str(value or "").strip().casefold().split())


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
