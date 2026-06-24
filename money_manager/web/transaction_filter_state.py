from __future__ import annotations

from typing import Any, Iterable

from flask import session

SESSION_KEY = "transaction_filter_state"
SESSION_VERSION = 3
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
        "version": SESSION_VERSION,
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

    # Ignore old sessions created by previous versions of the filter logic.
    # This fixes stale browser sessions where the saved date range was the first
    # transaction ever, which made Dashboard/Transactions open in all-history
    # mode even though the default display should be the current year.
    if int(saved.get("version") or 0) != SESSION_VERSION:
        session.pop(SESSION_KEY, None)
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
        "version": SESSION_VERSION,
        "start": str(args.get("from", defaults["start"]) or defaults["start"]),
        "end": str(args.get("to", defaults["end"]) or defaults["end"]),
        "types": _clean_list(submitted_types) or defaults["types"],
        "categories": _clean_list(submitted_categories),
        "query": str(args.get("q", "") or "").strip(),
        "amount_min": str(args.get("amount_min", "") or "").strip(),
        "amount_max": str(args.get("amount_max", "") or "").strip(),
    }


def has_date_transaction_filter(state: dict[str, Any], start_default: str, end_default: str) -> bool:
    return str(state.get("start") or "") != str(start_default) or str(state.get("end") or "") != str(end_default)


def has_non_date_transaction_filters(
    state: dict[str, Any],
    all_types: Iterable[str],
) -> bool:
    default_types = sorted(_clean_list(all_types))
    active_types = sorted(_clean_list(state.get("types") or [])) or default_types

    return any([
        active_types != default_types,
        bool(_clean_list(state.get("categories") or [])),
        bool(str(state.get("query") or "").strip()),
        bool(str(state.get("amount_min") or "").strip()),
        bool(str(state.get("amount_max") or "").strip()),
    ])


def has_effective_transaction_filters(
    state: dict[str, Any],
    start_default: str,
    end_default: str,
    all_types: Iterable[str],
) -> bool:
    """Return True only when the user narrowed the calculation scope.

    The app intentionally uses a January-1st default date window for display so
    tables/charts do not become huge. That default window must not be mistaken
    for a real money-calculation filter, otherwise opening balances and older
    transactions disappear from the tracked net.
    """
    return has_date_transaction_filter(state, start_default, end_default) or has_non_date_transaction_filters(state, all_types)


def _with_calculation_metadata(
    state: dict[str, Any],
    start_default: str,
    end_default: str,
    all_types: Iterable[str],
) -> dict[str, Any]:
    state = dict(state)
    has_date_filters = has_date_transaction_filter(state, start_default, end_default)
    has_non_date_filters = has_non_date_transaction_filters(state, all_types)
    has_filters = has_date_filters or has_non_date_filters
    state["has_effective_filters"] = has_filters
    state["has_date_filters"] = has_date_filters
    state["has_non_date_filters"] = has_non_date_filters
    state["uses_full_history_for_calculations"] = not has_filters
    state["calculation_scope_label"] = "selected filters" if has_filters else "full history"
    state["display_scope_label"] = "selected filters" if has_filters else "previous month + current month"
    return state


def resolve_transaction_filter_state(args: Any, start_default: str, end_default: str, all_types: Iterable[str]) -> dict[str, Any]:
    """Return the active transaction filter state for Dashboard/Transactions.

    Default behavior is deliberately split:
    - visual scope: current year, so tables/charts stay readable;
    - money scope: full history, so older opening rows still count.

    If the user submits filters/date range, both visual scope and money scope
    follow the selected filters. Reset returns to rolling-window visuals plus
    historical initial-condition money calculations.
    """
    if _should_reset(args):
        session.pop(SESSION_KEY, None)
        return _with_calculation_metadata(_default_state(start_default, end_default, all_types), start_default, end_default, all_types)

    if _has_filter_args(args):
        state = _state_from_args(args, start_default, end_default, all_types)
        session[SESSION_KEY] = state
        return _with_calculation_metadata(state, start_default, end_default, all_types)

    saved_state = _state_from_session(start_default, end_default, all_types)
    if saved_state is not None:
        return _with_calculation_metadata(saved_state, start_default, end_default, all_types)

    return _with_calculation_metadata(_default_state(start_default, end_default, all_types), start_default, end_default, all_types)
