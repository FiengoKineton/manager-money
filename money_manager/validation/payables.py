from __future__ import annotations

from typing import Mapping, Any

from money_manager.validation.common import ValidationError, parse_optional_amount, parse_positive_amount, result, ValidationResult


def validate_payable_payload(payload: Mapping[str, Any]) -> ValidationResult:
    errors: list[ValidationError] = []
    parse_positive_amount(payload, "amount", errors, label="Amount")
    parse_optional_amount(payload, "paid_amount", errors, label="Paid amount")
    return result(errors)
