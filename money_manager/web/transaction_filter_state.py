from __future__ import annotations

from typing import Any, Iterable

from flask import session

SESSION_KEY = "transaction_filter_state"
FILTER_PARAM_NAMES = {"from", "to", "types", "category", "q", "amount_min", "amount_max"}
RESET_PARAM_NAMES = {"reset_filters", "clear_filters"}


def _clean_list(values: Iterable[Any]) -> list[str]:
    cleaned: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def _default_state(start_default: str, end_default: str, all_types: Iterable[str]) -> dict[str, Any]:
    return {
        "start": start_default,
        "end": end_default,
        "types": list(all_types),
        "categories": [],
        "query": "",
        "amount_min": "",
        "amount_max": "",
    }


def _has_filter_args(args: Any) -> bool:
    return any(name in args for name in FILTER_PARAM_NAMES)


def _should_reset(args: Any) -> bool:
    return any(str(args.get(name, "")).strip() for name in RESET_PARAM_NAMES if name in args)


def _state_from_session(start_default: str, end_default: str, all_types: Iterable[str]) -> dict[str, Any] | None:
    saved = session.get(SESSION_KEY)
    if not isinstance(saved, dict):
        return None

    defaults = _default_state(start_default, end_default, all_types)
    state = defaults.copy()
    state.update({
        "start": str(saved.get("start") or defaults["start"]),
        "end": str(saved.get("end") or defaults["end"]),
        "types": _clean_list(saved.get("types") or defaults["types"]) or defaults["types"],
        "categories": _clean_list(saved.get("categories") or []),
        "query": str(saved.get("query") or "").strip(),
        "amount_min": str(saved.get("amount_min") or "").strip(),
        "amount_max": str(saved.get("amount_max") or "").strip(),
    })
    return state


def _state_from_args(args: Any, start_default: str, end_default: str, all_types: Iterable[str]) -> dict[str, Any]:
    defaults = _default_state(start_default, end_default, all_types)

    # Keep the old behavior: if no type checkbox is submitted, treat it as all
    # transaction types instead of filtering everything out.
    submitted_types = args.getlist("types") if hasattr(args, "getlist") else []
    submitted_categories = args.getlist("category") if hasattr(args, "getlist") else []

    return {
        "start": str(args.get("from", defaults["start"]) or defaults["start"]),
        "end": str(args.get("to", defaults["end"]) or defaults["end"]),
        "types": _clean_list(submitted_types) or defaults["types"],
        "categories": _clean_list(submitted_categories),
        "query": str(args.get("q", "") or "").strip(),
        "amount_min": str(args.get("amount_min", "") or "").strip(),
        "amount_max": str(args.get("amount_max", "") or "").strip(),
    }


def resolve_transaction_filter_state(args: Any, start_default: str, end_default: str, all_types: Iterable[str]) -> dict[str, Any]:
    """Return the active transaction filter state for Dashboard/Transactions.

    The filter form still uses normal GET parameters, but the latest submitted
    values are also stored in the Flask session. This lets the same filtered set
    survive navigation to transaction details, edits, deletes, and switching
    between Dashboard and Transactions. The state is cleared only when the user
    explicitly presses the All button.
    """
    if _should_reset(args):
        session.pop(SESSION_KEY, None)
        return _default_state(start_default, end_default, all_types)

    if _has_filter_args(args):
        state = _state_from_args(args, start_default, end_default, all_types)
        session[SESSION_KEY] = state
        return state

    saved_state = _state_from_session(start_default, end_default, all_types)
    if saved_state is not None:
        return saved_state

    return _default_state(start_default, end_default, all_types)
