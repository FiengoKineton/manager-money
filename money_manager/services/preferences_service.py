from __future__ import annotations

from typing import Any, Mapping

from money_manager.config.user_defaults import DEFAULT_PREFERENCES
from money_manager.services._user_config import load_user_config, save_user_config, safe_update_fields, utc_now

PREFERENCES_FILE = "preferences.json"
KNOWN_PREFERENCE_FIELDS = {
    "theme",
    "language",
    "currency",
    "date_format",
    "privacy_mode",
    "show_sensitive_data",
    "onboarding_completed",
}
THEME_VALUES = {"day", "night", "comfort"}
THEME_ALIASES = {
    "light": "day",
    "day": "day",
    "dark": "night",
    "night": "night",
    "comfort": "comfort",
    "eye": "comfort",
    "eye_comfort": "comfort",
    "eye-comfort": "comfort",
}


def load_preferences(user_id: str | None = None) -> dict[str, Any]:
    return _normalize_preferences(load_user_config(PREFERENCES_FILE, user_id=user_id))


def save_preferences(preferences: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    payload = _normalize_preferences(dict(preferences or {}))
    payload["updated_at"] = utc_now()
    return save_user_config(PREFERENCES_FILE, payload, user_id=user_id)


def update_preferences(
    updates: Mapping[str, Any],
    user_id: str | None = None,
    *,
    allow_future_fields: bool = True,
) -> dict[str, Any]:
    preferences = load_preferences(user_id=user_id)
    preferences = safe_update_fields(
        preferences,
        updates,
        allowed_fields=KNOWN_PREFERENCE_FIELDS,
        allow_unknown=allow_future_fields,
    )
    return save_preferences(preferences, user_id=user_id)


def ensure_preferences_config(user_id: str | None = None) -> dict[str, Any]:
    preferences = load_preferences(user_id=user_id)
    if not preferences.get("updated_at"):
        preferences["updated_at"] = utc_now()
        return save_user_config(PREFERENCES_FILE, preferences, user_id=user_id)
    return preferences


def _normalize_preferences(preferences: Mapping[str, Any]) -> dict[str, Any]:
    clean = dict(DEFAULT_PREFERENCES)
    clean.update(dict(preferences or {}))
    clean["theme"] = normalize_theme_value(clean.get("theme"), default="day")
    clean["language"] = str(clean.get("language") or "en").strip() or "en"
    clean["currency"] = str(clean.get("currency") or "EUR").strip().upper() or "EUR"
    clean["date_format"] = str(clean.get("date_format") or "dd/mm/yyyy").strip() or "dd/mm/yyyy"
    clean["privacy_mode"] = _as_bool(clean.get("privacy_mode", False), default=False)
    clean["show_sensitive_data"] = _as_bool(clean.get("show_sensitive_data", True), default=True)
    clean["onboarding_completed"] = _as_bool(clean.get("onboarding_completed", True), default=True)
    clean["updated_at"] = str(clean.get("updated_at") or "")
    if not clean.get("schema_version"):
        clean["schema_version"] = DEFAULT_PREFERENCES["schema_version"]
    return clean


def normalize_theme_value(value: Any, *, default: str = "day") -> str:
    clean = str(value or default or "day").strip().casefold().replace(" ", "_")
    return THEME_ALIASES.get(clean, default if default in THEME_VALUES else "day")


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
