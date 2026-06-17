from __future__ import annotations

from typing import Mapping, Any

from money_manager.validation.common import ValidationError, parse_iso_date, parse_positive_amount, result, ValidationResult


def validate_recurring_payload(payload: Mapping[str, Any]) -> ValidationResult:
    errors: list[ValidationError] = []
    parse_positive_amount(payload, "amount", errors, label="Amount")
    if payload.get("start_date"):
        parse_iso_date(payload, "start_date", errors, label="Start date")
    if payload.get("end_date"):
        parse_iso_date(payload, "end_date", errors, label="End date")
    return result(errors)
