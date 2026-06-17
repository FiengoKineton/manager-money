from __future__ import annotations

from typing import Mapping, Any

from money_manager.validation.common import ValidationError, parse_optional_amount, require_text, result, ValidationResult


def validate_project_payload(payload: Mapping[str, Any]) -> ValidationResult:
    errors: list[ValidationError] = []
    require_text(payload, "name", errors, label="Project name")
    parse_optional_amount(payload, "expected_cost", errors, label="Expected cost")
    return result(errors)
