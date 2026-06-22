from __future__ import annotations

import json
from pathlib import Path
from string import Formatter
from typing import Any

from money_manager.services.preferences_service import load_preferences

I18N_DIR = Path(__file__).resolve().parents[1] / "i18n"
DEFAULT_LANGUAGE = "en"
_AVAILABLE_LANGUAGES: dict[str, str] = {
    "en": "English",
    "it": "Italiano",
}
_TRANSLATION_CACHE: dict[str, dict[str, Any]] = {}
_MTIME_CACHE: dict[str, float | None] = {}


class _SafeFormatDict(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def available_languages() -> dict[str, str]:
    """Return language codes shown in the UI."""
    return dict(_AVAILABLE_LANGUAGES)


def available_language_codes() -> set[str]:
    return set(_AVAILABLE_LANGUAGES)


def normalize_language(language: str | None) -> str:
    code = str(language or "").strip().casefold()
    return code if code in _AVAILABLE_LANGUAGES else DEFAULT_LANGUAGE


def current_language() -> str:
    """Return the selected language for the current user, falling back to English."""
    try:
        preferences = load_preferences()
    except Exception:
        return DEFAULT_LANGUAGE
    return normalize_language(str(preferences.get("language") or DEFAULT_LANGUAGE))


def t(key: str, **kwargs: Any) -> str:
    """Translate a key for the current user and safely format placeholders.

    Missing language files fall back to English. Missing keys fall back to the
    key itself, so templates keep rendering even while translations are being
    added incrementally.
    """
    text_key = str(key or "")
    language = current_language()
    template = _lookup(language, text_key)
    if kwargs:
        try:
            return template.format_map(_SafeFormatDict(kwargs))
        except Exception:
            return template
    return template


def translate_for(language: str | None, key: str, **kwargs: Any) -> str:
    """Translate using an explicit language code. Useful for tests and scripts."""
    text_key = str(key or "")
    template = _lookup(normalize_language(language), text_key)
    if kwargs:
        try:
            return template.format_map(_SafeFormatDict(kwargs))
        except Exception:
            return template
    return template


def _lookup(language: str, key: str) -> str:
    translations = _load_language(language)
    value = translations.get(key)
    if value is None and language != DEFAULT_LANGUAGE:
        value = _load_language(DEFAULT_LANGUAGE).get(key)
    if value is None:
        return key
    return str(value)


def _load_language(language: str) -> dict[str, Any]:
    code = normalize_language(language)
    path = I18N_DIR / f"{code}.json"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        if code == DEFAULT_LANGUAGE:
            return {}
        return _load_language(DEFAULT_LANGUAGE)

    cached = _TRANSLATION_CACHE.get(code)
    if cached is not None and _MTIME_CACHE.get(code) == mtime:
        return cached

    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    _TRANSLATION_CACHE[code] = payload
    _MTIME_CACHE[code] = mtime
    return payload
