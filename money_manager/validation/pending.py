from __future__ import annotations

from typing import Mapping, Any

from money_manager.validation.common import ValidationError, parse_iso_date, parse_positive_amount, result, ValidationResult


def validate_pending_payload(payload: Mapping[str, Any]) -> ValidationResult:
    errors: list[ValidationError] = []
    parse_iso_date(payload, "due_date", errors, label="Due date")
    parse_positive_amount(payload, "amount", errors, label="Amount")
    return result(errors)
