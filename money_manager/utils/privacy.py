from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping


def compute_initials(
    first_name: str | None = "",
    last_name: str | None = "",
    display_name: str | None = "",
    username: str | None = "",
) -> str:
    names = [str(first_name or "").strip(), str(last_name or "").strip()]
    initials = "".join(part[0] for part in names if part)
    if not initials:
        source = str(display_name or "").strip() or str(username or "").strip()
        pieces = [piece for piece in source.replace("_", " ").replace("-", " ").split() if piece]
        if len(pieces) >= 2:
            initials = pieces[0][0] + pieces[-1][0]
        elif pieces:
            initials = pieces[0][:2]
    return (initials or "U").upper()[:2]


def should_mask_sensitive(preferences: Mapping[str, Any] | None = None, user_id: str | None = None) -> bool:
    """Return True when sensitive values should be hidden in the UI.

    Privacy mode only affects display.  Data, calculations and backups remain
    unchanged.  show_sensitive_data acts as the deliberate reveal switch.
    """
    prefs: Mapping[str, Any]
    if preferences is None:
        try:
            from money_manager.services.preferences_service import load_preferences

            prefs = load_preferences(user_id=user_id)
        except Exception:
            return False
    else:
        prefs = preferences
    privacy_mode = _as_bool(prefs.get("privacy_mode", False), default=False)
    show_sensitive = _as_bool(prefs.get("show_sensitive_data", True), default=True)
    return privacy_mode and not show_sensitive


def mask_iban(iban: str | None) -> str:
    raw = "".join(str(iban or "").split())
    if not raw:
        return ""
    if len(raw) <= 8:
        return "••••"
    masked = f"{raw[:4]}{'•' * max(len(raw) - 8, 4)}{raw[-4:]}"
    return " ".join(masked[index : index + 4] for index in range(0, len(masked), 4))


def mask_text(value: Any, preferences: Mapping[str, Any] | None = None, *, mask: str = "••••") -> str:
    text = str(value or "")
    if not text:
        return ""
    return mask if should_mask_sensitive(preferences) else text


def mask_amount(value: Any, privacy_mode: bool = False, *, mask: str = "••••") -> Any:
    if privacy_mode:
        return mask
    return value


def mask_money(
    value: Any,
    preferences: Mapping[str, Any] | None = None,
    *,
    currency: str | None = None,
    mask: str = "••••",
) -> str:
    if should_mask_sensitive(preferences):
        return mask
    return format_money(value, currency=currency)


def format_money(value: Any, *, currency: str | None = None) -> str:
    try:
        amount = Decimal(str(value or 0).replace("€", "").replace(",", ""))
    except (InvalidOperation, ValueError):
        return str(value or "")
    code = str(currency or "EUR").upper()
    symbol = "€" if code == "EUR" else code
    return f"{symbol} {amount:,.2f}"


def format_masked_amount(value: Any, privacy_mode: bool = False, currency: str = "EUR") -> str:
    if privacy_mode:
        return "••••"
    return format_money(value, currency=currency)


def safe_update_fields(
    current: Mapping[str, Any],
    updates: Mapping[str, Any],
    *,
    allowed_fields: Iterable[str] | None = None,
    allow_unknown: bool = False,
) -> dict[str, Any]:
    result = deepcopy(dict(current or {}))
    allowed = set(allowed_fields or [])
    for key, value in dict(updates or {}).items():
        key_text = str(key or "").strip()
        if not key_text or key_text.startswith("_"):
            continue
        if allowed and key_text not in allowed and not allow_unknown:
            continue
        if isinstance(value, (str, int, float, bool, list, dict)) or value is None:
            result[key_text] = value
    return result


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
