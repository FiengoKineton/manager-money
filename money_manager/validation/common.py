from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Mapping


@dataclass(frozen=True)
class ValidationError:
    field: str
    message: str


@dataclass(frozen=True)
class ValidationResult:
    errors: tuple[ValidationError, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, list[str]]:
        grouped: dict[str, list[str]] = {}
        for error in self.errors:
            grouped.setdefault(error.field, []).append(error.message)
        return grouped


def result(errors: list[ValidationError]) -> ValidationResult:
    return ValidationResult(errors=tuple(errors))


def require_text(payload: Mapping[str, Any], field: str, errors: list[ValidationError], *, label: str | None = None) -> str:
    value = str(payload.get(field, "") or "").strip()
    if not value:
        errors.append(ValidationError(field, f"{label or field} is required."))
    return value


def parse_positive_amount(payload: Mapping[str, Any], field: str, errors: list[ValidationError], *, label: str | None = None) -> float:
    raw = payload.get(field, "")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        errors.append(ValidationError(field, f"{label or field} must be a number."))
        return 0.0
    if value <= 0:
        errors.append(ValidationError(field, f"{label or field} must be greater than zero."))
    return value


def parse_optional_amount(payload: Mapping[str, Any], field: str, errors: list[ValidationError], *, label: str | None = None) -> float | None:
    raw = payload.get(field, "")
    if raw in (None, ""):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        errors.append(ValidationError(field, f"{label or field} must be a number."))
        return None


def parse_iso_date(payload: Mapping[str, Any], field: str, errors: list[ValidationError], *, label: str | None = None) -> str:
    value = str(payload.get(field, "") or "").strip()
    try:
        date.fromisoformat(value)
    except (TypeError, ValueError):
        errors.append(ValidationError(field, f"{label or field} must be a valid YYYY-MM-DD date."))
    return value


def require_choice(payload: Mapping[str, Any], field: str, allowed: set[str], errors: list[ValidationError], *, label: str | None = None) -> str:
    value = str(payload.get(field, "") or "").strip()
    if value not in allowed:
        errors.append(ValidationError(field, f"{label or field} must be one of: {', '.join(sorted(allowed))}."))
    return value
