from __future__ import annotations

from typing import Mapping, Any

from money_manager.config import TRANSACTION_TYPES
from money_manager.validation.common import ValidationError, parse_iso_date, parse_positive_amount, require_choice, result, ValidationResult


def validate_transaction_payload(payload: Mapping[str, Any]) -> ValidationResult:
    errors: list[ValidationError] = []
    require_choice(payload, "type", set(TRANSACTION_TYPES), errors, label="Transaction type")
    parse_iso_date(payload, "date", errors, label="Date")
    parse_positive_amount(payload, "amount", errors, label="Amount")
    return result(errors)
