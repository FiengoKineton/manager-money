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


def mask_iban(iban: str | None) -> str:
    raw = "".join(str(iban or "").split())
    if not raw:
        return ""
    if len(raw) <= 8:
        return "••••"
    masked = f"{raw[:4]}{'•' * max(len(raw) - 8, 4)}{raw[-4:]}"
    return " ".join(masked[index : index + 4] for index in range(0, len(masked), 4))


def mask_amount(value: Any, privacy_mode: bool = False, *, mask: str = "••••") -> Any:
    if privacy_mode:
        return mask
    return value


def format_masked_amount(value: Any, privacy_mode: bool = False, currency: str = "EUR") -> str:
    if privacy_mode:
        return "••••"
    try:
        amount = Decimal(str(value or 0))
    except (InvalidOperation, ValueError):
        return str(value or "")
    symbol = "€" if str(currency).upper() == "EUR" else str(currency).upper()
    return f"{symbol}{amount:,.2f}"


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
