from __future__ import annotations

from calendar import monthrange
from datetime import date
from typing import Any, Iterable

import pandas as pd


def _clean_list(values: Iterable[Any]) -> list[str]:
    cleaned: list[str] = []
    for value in values or []:
        text = str(value or "").strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def _safe_year(value: Any, available_years: list[int]) -> int:
    current_year = date.today().year
    try:
        year = int(str(value or "").strip())
    except (TypeError, ValueError):
        year = current_year
    if available_years and year not in available_years:
        return current_year if current_year in available_years else available_years[-1]
    return year


def _safe_month(value: Any) -> int:
    try:
        month = int(str(value or "").strip())
    except (TypeError, ValueError):
        month = date.today().month
    return min(12, max(1, month))


def dashboard_period_state(args: Any, scoped_df: pd.DataFrame | None) -> dict[str, Any]:
    """Resolve a query-only full-history/month selector.

    Nothing is written to the session. The selection therefore applies only to
    the current Dashboard or Transactions URL and naturally disappears as soon
    as the user navigates to another page.
    """
    dated = scoped_df.copy() if scoped_df is not None else pd.DataFrame()
    if "date" in dated.columns:
        dated["date"] = pd.to_datetime(dated["date"], errors="coerce")
        valid_dates = dated["date"].dropna()
    else:
        valid_dates = pd.Series(dtype="datetime64[ns]")

    available_years = sorted({int(value) for value in valid_dates.dt.year.tolist()}) if not valid_dates.empty else []
    if date.today().year not in available_years:
        available_years.append(date.today().year)
        available_years.sort()

    mode = str(args.get("period_mode") or "all").strip().casefold()
    if mode not in {"all", "month"}:
        mode = "all"

    selected_year = _safe_year(args.get("period_year"), available_years)
    selected_month = _safe_month(args.get("period_month"))

    if mode == "month":
        start = date(selected_year, selected_month, 1).isoformat()
        end = date(selected_year, selected_month, monthrange(selected_year, selected_month)[1]).isoformat()
        label = date(selected_year, selected_month, 1).strftime("%B %Y")
    elif not valid_dates.empty:
        start = valid_dates.min().date().isoformat()
        end = valid_dates.max().date().isoformat()
        label = "first log → latest log"
    else:
        today = date.today().isoformat()
        start = today
        end = today
        label = "all available logs"

    return {
        "mode": mode,
        "start": start,
        "end": end,
        "year": selected_year,
        "month": selected_month,
        "label": label,
        "available_years": available_years,
        "month_options": [
            {"value": month, "label": date(2000, month, 1).strftime("%B")}
            for month in range(1, 13)
        ],
    }


def dashboard_query_filter_state(
    args: Any,
    scoped_df: pd.DataFrame | None,
    all_types: Iterable[str],
) -> dict[str, Any]:
    """Build Dashboard/Transactions filters without persistent browser state."""
    period = dashboard_period_state(args, scoped_df)
    default_types = _clean_list(all_types)
    submitted_types = args.getlist("types") if hasattr(args, "getlist") else []
    submitted_categories = args.getlist("category") if hasattr(args, "getlist") else []
    types = _clean_list(submitted_types) or default_types
    categories = _clean_list(submitted_categories)
    query = str(args.get("q") or "").strip()
    amount_min = str(args.get("amount_min") or "").strip()
    amount_max = str(args.get("amount_max") or "").strip()
    has_non_date_filters = any([
        sorted(types) != sorted(default_types),
        bool(categories),
        bool(query),
        bool(amount_min),
        bool(amount_max),
    ])
    return {
        "start": period["start"],
        "end": period["end"],
        "types": types,
        "categories": categories,
        "query": query,
        "amount_min": amount_min,
        "amount_max": amount_max,
        "period": period,
        "has_date_filters": period["mode"] == "month",
        "has_non_date_filters": has_non_date_filters,
        "has_effective_filters": period["mode"] == "month" or has_non_date_filters,
        "uses_full_history_for_calculations": period["mode"] == "all",
        "calculation_scope_label": period["label"],
        "display_scope_label": period["label"],
    }
