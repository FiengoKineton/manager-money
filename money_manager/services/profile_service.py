from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

from money_manager.config.user_defaults import DEFAULT_PROFILE
from money_manager.services._user_config import load_user_config, save_user_config, safe_update_fields, utc_now
from money_manager.utils.privacy import compute_initials, mask_iban

PROFILE_FILE = "profile.json"
PROFILE_UPDATE_FIELDS = {
    "first_name",
    "last_name",
    "display_name",
    "birth_year",
    "bank_name",
    "iban",
    "bic_swift",
    "default_main_account",
    "profile_image",
}


def load_profile(user_id: str | None = None) -> dict[str, Any]:
    profile = load_user_config(PROFILE_FILE, user_id=user_id)
    return _normalize_profile(profile)


def save_profile(profile: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    payload = _normalize_profile(dict(profile or {}))
    if not payload.get("created_at"):
        payload["created_at"] = utc_now()
    payload["updated_at"] = utc_now()
    return save_user_config(PROFILE_FILE, payload, user_id=user_id)


def update_profile(updates: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    profile = load_profile(user_id=user_id)
    profile = safe_update_fields(profile, updates, allowed_fields=PROFILE_UPDATE_FIELDS)
    return save_profile(profile, user_id=user_id)


def ensure_profile_config(user_id: str | None = None, user_hint: Mapping[str, Any] | None = None) -> dict[str, Any]:
    profile = load_profile(user_id=user_id)
    changed = False
    now = utc_now()
    if not profile.get("created_at"):
        profile["created_at"] = now
        changed = True
    if user_hint:
        for field in ("first_name", "last_name", "display_name"):
            if not str(profile.get(field) or "").strip() and str(user_hint.get(field) or "").strip():
                profile[field] = str(user_hint.get(field) or "").strip()
                changed = True
    if changed:
        profile["updated_at"] = now
        return save_user_config(PROFILE_FILE, profile, user_id=user_id)
    return profile


def display_name_from_profile(profile: Mapping[str, Any] | None, username: str | None = "") -> str:
    profile = profile or {}
    display = str(profile.get("display_name") or "").strip()
    if display:
        return display
    first = str(profile.get("first_name") or "").strip()
    last = str(profile.get("last_name") or "").strip()
    full_name = " ".join(part for part in (first, last) if part).strip()
    return full_name or str(username or "").strip() or "User"


def initials_from_profile(profile: Mapping[str, Any] | None, username: str | None = "") -> str:
    profile = profile or {}
    return compute_initials(
        first_name=str(profile.get("first_name") or ""),
        last_name=str(profile.get("last_name") or ""),
        display_name=str(profile.get("display_name") or ""),
        username=username,
    )


def profile_public_summary(profile: Mapping[str, Any] | None, username: str | None = "") -> dict[str, Any]:
    profile = dict(profile or DEFAULT_PROFILE)
    return {
        "display_name": display_name_from_profile(profile, username=username),
        "initials": initials_from_profile(profile, username=username),
        "bank_name": str(profile.get("bank_name") or ""),
        "iban_masked": mask_iban(str(profile.get("iban") or "")),
        "profile_image": str(profile.get("profile_image") or ""),
    }


def _normalize_profile(profile: Mapping[str, Any]) -> dict[str, Any]:
    clean = dict(DEFAULT_PROFILE)
    clean.update(dict(profile or {}))
    for field in PROFILE_UPDATE_FIELDS | {"created_at", "updated_at"}:
        if clean.get(field) is None:
            clean[field] = ""
        clean[field] = str(clean.get(field) or "").strip()
    clean["profile_image"] = _clean_profile_image(clean.get("profile_image"))
    if not clean.get("schema_version"):
        clean["schema_version"] = DEFAULT_PROFILE["schema_version"]
    return clean


def _clean_profile_image(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if ".." in text or "/" in text or "\\" in text or Path(text).is_absolute():
        return ""
    safe = re.sub(r"[^A-Za-z0-9_. -]+", "_", text).strip(" ._")
    return safe[:160]
