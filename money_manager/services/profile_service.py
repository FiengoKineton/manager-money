from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from money_manager.config.user_defaults import DEFAULT_PROFILE
from money_manager.config.user_paths import get_user_data_dir
from money_manager.security.protection_manager import read_json, write_json_atomic
from money_manager.services._user_config import load_user_config, save_user_config, safe_update_fields, utc_now
from money_manager.utils.privacy import compute_initials, mask_iban

PROFILE_FILE = "profile.json"
PROFILE_UPDATE_FIELDS = {
    # Personal fields.
    "first_name",
    "last_name",
    "display_name",
    "birth_year",
    "profile_image",
    "profile_notes",
    # Professional account/payment defaults.
    "default_current_account_id",
    "default_payment_method_id",
    "onboarding_completed",
    # Deprecated compatibility fields. Kept writable so old imports/pages remain safe.
    "bank_name",
    "iban",
    "bic_swift",
    "default_main_account",
}
DEPRECATED_PROFILE_BANK_FIELDS = {"bank_name", "iban", "bic_swift", "default_main_account"}
_PROFILE_BANK_MIGRATION_FLAG = "profile_bank_fields_migration"


def load_profile(user_id: str | None = None) -> dict[str, Any]:
    profile = _normalize_profile(load_user_config(PROFILE_FILE, user_id=user_id))
    migrate_profile_bank_info(profile, user_id=user_id)
    return _normalize_profile(load_user_config(PROFILE_FILE, user_id=user_id))


def save_profile(profile: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    payload = _normalize_profile(dict(profile or {}))
    if not payload.get("created_at"):
        payload["created_at"] = utc_now()
    payload["updated_at"] = utc_now()
    return save_user_config(PROFILE_FILE, payload, user_id=user_id)


def update_profile(updates: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    profile = load_profile(user_id=user_id)
    profile = safe_update_fields(profile, updates, allowed_fields=PROFILE_UPDATE_FIELDS)
    saved = save_profile(profile, user_id=user_id)
    migrate_profile_bank_info(saved, user_id=user_id)
    return load_profile(user_id=user_id)


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
        saved = save_user_config(PROFILE_FILE, profile, user_id=user_id)
        migrate_profile_bank_info(saved, user_id=user_id)
        return load_profile(user_id=user_id)
    return profile


def migrate_profile_bank_info(profile: Mapping[str, Any] | None = None, user_id: str | None = None) -> dict[str, Any]:
    """Copy legacy profile bank fields into the default current account when safe.

    The legacy fields remain in profile.json for compatibility, but account ownership
    now lives on account records. Ambiguous cases are not guessed; they are recorded
    in migration_info.json and later exposed by the integrity report.
    """
    profile = _normalize_profile(profile or load_user_config(PROFILE_FILE, user_id=user_id))
    legacy_values = {
        "institution": str(profile.get("bank_name") or "").strip(),
        "iban": str(profile.get("iban") or "").strip(),
        "bic_swift": str(profile.get("bic_swift") or "").strip(),
    }
    if not any(legacy_values.values()):
        return {"ok": True, "changed": False, "reason": "no_legacy_bank_fields"}

    try:
        from money_manager.services.account_config_service import MAIN_ACCOUNT_KEY, load_accounts_config, save_accounts_config
    except Exception as exc:
        return {"ok": False, "changed": False, "reason": f"account_service_unavailable:{exc}"}

    config = load_accounts_config(user_id=user_id)
    accounts = [account for account in config.get("accounts", []) if isinstance(account, dict)]
    by_key = {str(account.get("key") or account.get("id") or ""): account for account in accounts}
    current_accounts = [
        account for account in accounts
        if bool(account.get("is_current_account")) or str(account.get("account_kind") or account.get("type") or "") == "current_account"
    ]

    requested_target = str(profile.get("default_current_account_id") or profile.get("default_main_account") or "").strip()
    target_key = requested_target if requested_target in by_key else ""
    if not target_key and MAIN_ACCOUNT_KEY in by_key:
        target_key = MAIN_ACCOUNT_KEY

    if not target_key or target_key not in by_key:
        _write_profile_bank_migration_note(
            user_id,
            ok=False,
            changed=False,
            target_account_id="",
            notes=["Legacy profile bank fields could not be migrated because no default current account/main_bank account exists."],
        )
        return {"ok": False, "changed": False, "reason": "missing_default_current_account"}

    target = by_key[target_key]
    target_is_current = bool(target.get("is_current_account")) or str(target.get("account_kind") or target.get("type") or "") == "current_account"
    if not target_is_current:
        _write_profile_bank_migration_note(
            user_id,
            ok=False,
            changed=False,
            target_account_id=target_key,
            notes=[f"Legacy profile bank fields were not migrated because {target_key} is not a current account."],
        )
        return {"ok": False, "changed": False, "reason": "target_not_current_account"}

    # If the profile has no explicit default and more than one current account exists,
    # only main_bank is considered safe. Anything else would be a guess.
    if not requested_target and len(current_accounts) > 1 and target_key != MAIN_ACCOUNT_KEY:
        _write_profile_bank_migration_note(
            user_id,
            ok=False,
            changed=False,
            target_account_id=target_key,
            notes=["Multiple current accounts exist and profile has no default_current_account_id; bank fields were left in profile."],
        )
        return {"ok": False, "changed": False, "reason": "ambiguous_current_accounts"}

    changed_fields: list[str] = []
    mapping = {"bank_name": "institution", "iban": "iban", "bic_swift": "bic_swift"}
    for legacy_field, account_field in mapping.items():
        value = str(profile.get(legacy_field) or "").strip()
        if value and not str(target.get(account_field) or "").strip():
            target[account_field] = value
            changed_fields.append(account_field)

    notes: list[str] = []
    if changed_fields:
        target["updated_at"] = utc_now()
        config["accounts"] = accounts
        save_accounts_config(config, user_id=user_id)
        notes.append(
            f"Copied profile bank fields to account {target_key}: {', '.join(changed_fields)}. Legacy profile fields were kept as deprecated compatibility fields."
        )
    else:
        notes.append(
            f"Profile bank fields already had matching/non-empty account values on {target_key}; no overwrite was performed."
        )

    # Keep defaults coherent without deleting old fields.
    profile_changed = False
    if profile.get("default_current_account_id") != target_key:
        profile["default_current_account_id"] = target_key
        profile_changed = True
    if not profile.get("default_main_account"):
        profile["default_main_account"] = target_key
        profile_changed = True
    if profile_changed:
        profile["updated_at"] = utc_now()
        save_user_config(PROFILE_FILE, profile, user_id=user_id)

    _write_profile_bank_migration_note(
        user_id,
        ok=True,
        changed=bool(changed_fields or profile_changed),
        target_account_id=target_key,
        notes=notes,
    )
    return {"ok": True, "changed": bool(changed_fields or profile_changed), "target_account_id": target_key, "fields": changed_fields}


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
        "default_current_account_id": str(profile.get("default_current_account_id") or "main_bank"),
        "default_payment_method_id": str(profile.get("default_payment_method_id") or ""),
        "bank_name_deprecated": str(profile.get("bank_name") or ""),
        "iban_masked": mask_iban(str(profile.get("iban") or "")),
        "profile_image": str(profile.get("profile_image") or ""),
    }


def _normalize_profile(profile: Mapping[str, Any]) -> dict[str, Any]:
    clean = deepcopy(DEFAULT_PROFILE)
    clean.update(dict(profile or {}))

    text_fields = {
        "first_name",
        "last_name",
        "display_name",
        "birth_year",
        "bank_name",
        "iban",
        "bic_swift",
        "default_main_account",
        "default_current_account_id",
        "default_payment_method_id",
        "profile_notes",
        "created_at",
        "updated_at",
    }
    for field in text_fields:
        if clean.get(field) is None:
            clean[field] = ""
        clean[field] = str(clean.get(field) or "").strip()

    clean["profile_image"] = _clean_profile_image(clean.get("profile_image"))
    if not clean.get("default_current_account_id"):
        clean["default_current_account_id"] = clean.get("default_main_account") or "main_bank"
    if not clean.get("default_main_account"):
        clean["default_main_account"] = clean.get("default_current_account_id") or "main_bank"
    clean["onboarding_completed"] = _as_bool(clean.get("onboarding_completed", True), default=True)
    clean["deprecated_fields"] = sorted(set(clean.get("deprecated_fields") or []) | DEPRECATED_PROFILE_BANK_FIELDS)
    if not clean.get("schema_version") or int(clean.get("schema_version") or 0) < 2:
        clean["schema_version"] = DEFAULT_PROFILE["schema_version"]
    return clean


def _write_profile_bank_migration_note(
    user_id: str | None,
    *,
    ok: bool,
    changed: bool,
    target_account_id: str,
    notes: list[str],
) -> None:
    try:
        user_dir = get_user_data_dir(user_id)
    except RuntimeError:
        return
    path = user_dir / "migration_info.json"
    payload = read_json(path, {})
    if not isinstance(payload, dict):
        payload = {"schema_version": 1}
    existing = payload.get(_PROFILE_BANK_MIGRATION_FLAG)
    if isinstance(existing, dict) and existing.get("notes") == notes and existing.get("target_account_id") == target_account_id:
        return
    payload[_PROFILE_BANK_MIGRATION_FLAG] = {
        "ok": bool(ok),
        "changed": bool(changed),
        "target_account_id": target_account_id,
        "created_at": utc_now(),
        "notes": notes,
        "deprecated_profile_fields_kept": sorted(DEPRECATED_PROFILE_BANK_FIELDS),
    }
    write_json_atomic(path, payload)


def _clean_profile_image(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if ".." in text or "/" in text or "\\" in text or Path(text).is_absolute():
        return ""
    safe = re.sub(r"[^A-Za-z0-9_. -]+", "_", text).strip(" ._")
    return safe[:160]


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
