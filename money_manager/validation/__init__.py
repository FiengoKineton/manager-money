"""Passive validation helpers for forms and CSV-like payloads.

These helpers are intentionally not enforced globally yet.  They can be used by
new code and tests without changing existing app behaviour.
"""

from money_manager.validation.common import ValidationError, ValidationResult

__all__ = ["ValidationError", "ValidationResult"]
