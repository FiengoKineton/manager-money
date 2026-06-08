from __future__ import annotations

import re
from typing import Any


_NUMERIC_PERCENT_FORMAT = re.compile(r"^%([+\- 0#]*)?(\d+)?(?:\.(\d+))?([fF])$")


def _to_number(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def format_number(value: Any, decimals: int = 2, signed: bool = False) -> str:
    sign = "+" if signed else ""
    return f"{_to_number(value):{sign},.{decimals}f}"


def format_euro(value: Any, decimals: int = 2, signed: bool = False, space: bool = True) -> str:
    separator = " " if space else ""
    return f"€{separator}{format_number(value, decimals=decimals, signed=signed)}"


def thousands_format_filter(format_string: str, *args: Any, **kwargs: Any) -> str:
    if isinstance(format_string, str) and len(args) == 1 and not kwargs:
        match = _NUMERIC_PERCENT_FORMAT.match(format_string)
        if match:
            flags = match.group(1) or ""
            decimals = int(match.group(3) or 6)
            signed = "+" in flags
            return format_number(args[0], decimals=decimals, signed=signed)

    if kwargs:
        return format_string % kwargs
    if len(args) == 1:
        return format_string % args[0]
    return format_string % args