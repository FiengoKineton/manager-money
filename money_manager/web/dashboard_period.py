from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, time
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


def _safe_datetime_local(value: Any, fallback: datetime) -> datetime:
    text = str(value or "").strip()
    if not text:
        return fallback
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone().replace(tzinfo=None)
        return parsed
    except ValueError:
        try:
            return datetime.combine(date.fromisoformat(text[:10]), fallback.time())
        except ValueError:
            return fallback


def dashboard_period_state(
    args: Any,
    scoped_df: pd.DataFrame | None,
    *,
    available_years_override: Iterable[int] | None = None,
) -> dict[str, Any]:
    """Resolve a query-only all-history/month/exact-period selector."""
    dated = scoped_df.copy() if scoped_df is not None else pd.DataFrame()
    if "date" in dated.columns:
        dated["date"] = pd.to_datetime(dated["date"], errors="coerce")
        valid_dates = dated["date"].dropna()
    else:
        valid_dates = pd.Series(dtype="datetime64[ns]")

    override = [int(value) for value in (available_years_override or []) if str(value).isdigit()]
    available_years = sorted(set(override)) if override else (
        sorted({int(value) for value in valid_dates.dt.year.tolist()}) if not valid_dates.empty else []
    )
    if date.today().year not in available_years:
        available_years.append(date.today().year)
        available_years.sort()

    mode = str(args.get("period_mode") or "all").strip().casefold()
    if mode not in {"all", "month", "range"}:
        mode = "all"

    selected_year = _safe_year(args.get("period_year"), available_years)
    selected_month = _safe_month(args.get("period_month"))

    earliest = valid_dates.min().to_pydatetime() if not valid_dates.empty else datetime.combine(date.today(), time.min)
    latest = valid_dates.max().to_pydatetime() if not valid_dates.empty else datetime.combine(date.today(), time.max.replace(microsecond=0))
    default_range_start = datetime.combine(date.today().replace(day=1), time.min)
    default_range_end = datetime.combine(date.today(), time.max.replace(microsecond=0))
    range_start = _safe_datetime_local(args.get("period_start"), default_range_start)
    range_end = _safe_datetime_local(args.get("period_end"), default_range_end)
    if range_end < range_start:
        range_start, range_end = range_end, range_start

    if mode == "month":
        start_dt = datetime(selected_year, selected_month, 1, 0, 0, 0)
        end_dt = datetime(selected_year, selected_month, monthrange(selected_year, selected_month)[1], 23, 59, 59)
        label = date(selected_year, selected_month, 1).strftime("%B %Y")
    elif mode == "range":
        start_dt = range_start
        end_dt = range_end
        label = f"{start_dt.strftime('%Y-%m-%d %H:%M')} → {end_dt.strftime('%Y-%m-%d %H:%M')}"
    else:
        start_dt = earliest
        end_dt = latest
        label = "first log → latest log" if not valid_dates.empty or override else "all available logs"

    start_value = "" if mode == "all" and valid_dates.empty else start_dt.isoformat(timespec="seconds")
    end_value = "" if mode == "all" and valid_dates.empty else end_dt.isoformat(timespec="seconds")

    return {
        "mode": mode,
        "start": start_value,
        "end": end_value,
        "range_start": range_start.strftime("%Y-%m-%dT%H:%M"),
        "range_end": range_end.strftime("%Y-%m-%dT%H:%M"),
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
    *,
    available_years_override: Iterable[int] | None = None,
) -> dict[str, Any]:
    """Build Dashboard/Transactions filters without persistent browser state."""
    period = dashboard_period_state(args, scoped_df, available_years_override=available_years_override)
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
    has_date_filters = period["mode"] in {"month", "range"}
    return {
        "start": period["start"],
        "end": period["end"],
        "types": types,
        "categories": categories,
        "query": query,
        "amount_min": amount_min,
        "amount_max": amount_max,
        "period": period,
        "has_date_filters": has_date_filters,
        "has_non_date_filters": has_non_date_filters,
        "has_effective_filters": has_date_filters or has_non_date_filters,
        "uses_full_history_for_calculations": period["mode"] == "all",
        "calculation_scope_label": period["label"],
        "display_scope_label": period["label"],
    }
