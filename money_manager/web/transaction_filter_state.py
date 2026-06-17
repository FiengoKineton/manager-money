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
    default_types = sorted(_clean_list(all_types))
    active_types = sorted(_clean_list(state.get("types") or [])) or default_types

    return any([
        str(state.get("start") or "") != str(start_default),
        str(state.get("end") or "") != str(end_default),
        active_types != default_types,
        bool(_clean_list(state.get("categories") or [])),
        bool(str(state.get("query") or "").strip()),
        bool(str(state.get("amount_min") or "").strip()),
        bool(str(state.get("amount_max") or "").strip()),
    ])


def _with_calculation_metadata(
    state: dict[str, Any],
    start_default: str,
    end_default: str,
    all_types: Iterable[str],
) -> dict[str, Any]:
    state = dict(state)
    has_filters = has_effective_transaction_filters(state, start_default, end_default, all_types)
    state["has_effective_filters"] = has_filters
    state["uses_full_history_for_calculations"] = not has_filters
    state["calculation_scope_label"] = "selected filters" if has_filters else "full history"
    return state


def resolve_transaction_filter_state(args: Any, start_default: str, end_default: str, all_types: Iterable[str]) -> dict[str, Any]:
    """Return the active transaction filter state for Dashboard/Transactions.

    The filter form still uses normal GET parameters, but the latest submitted
    values are also stored in the Flask session. This lets the same filtered set
    survive navigation to transaction details, edits, deletes, and switching
    between Dashboard and Transactions. The state is cleared only when the user
    explicitly presses the All button.

    The returned metadata separates visual filtering from money calculations:
    the default Jan-1st→today display window is not treated as a calculation
    filter. Real balances use all historical rows unless the user actually
    changes date/type/category/search/amount filters.
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
