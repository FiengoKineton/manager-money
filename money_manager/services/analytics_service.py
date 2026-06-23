from __future__ import annotations

import math
from datetime import date, timedelta

import pandas as pd

from money_manager.config import default_date_range
from money_manager.repositories.debts import load_debts
from money_manager.repositories.payables import load_payables
from money_manager.repositories.pending import load_pending
from money_manager.repositories.receivables import load_receivables
from money_manager.repositories.recurring import load_recurring
from money_manager.services.account_scope_service import transactions_for_scope
from money_manager.services.investment_service import investment_habit_snapshot
from money_manager.services.forecast_service import estimate_cashflow_habits
from money_manager.utils.filters import filter_by_amount_range, filter_by_categories, filter_by_date, filter_by_query, filter_by_types
from money_manager.utils.interactive_plots import (
    chart_cashflow_waterfall,
    chart_cumulative_balance,
    chart_expenses_by_category,
    chart_income_sources,
    chart_monthly_savings_rate,
    chart_monthly_summary,
    chart_rolling_net_flow,
    chart_spending_pareto,
    chart_weekday_spending,
)
from money_manager.utils.plots import (
    plot_cumulative_balance,
    plot_expenses_by_category,
    plot_monthly_summary,
    plot_rolling_net_flow,
    plot_weekday_spending,
)
from money_manager.utils.stats import (
    cumulative_balance,
    expenses_by_category,
    largest_expenses,
    monthly_summary,
    period_income_expense,
    rolling_net_flow,
    summary_totals,
    weekday_spending,
)


PERIOD_OPTIONS = [
    {"key": "ytd", "label": "Current year", "small": "Jan 1 → today"},
    {"key": "last_90", "label": "90 days", "small": "Recent behaviour"},
    {"key": "last_180", "label": "6 months", "small": "Stable habits"},
    {"key": "last_365", "label": "12 months", "small": "Full annual rhythm"},
    {"key": "all", "label": "All time", "small": "Whole CSV history"},
]


def apply_transaction_filters(df: pd.DataFrame, start, end, types, categories, query, amount_min=None, amount_max=None) -> pd.DataFrame:
    filtered = df.copy()
    filtered = filter_by_date(filtered, start, end)
    filtered = filter_by_amount_range(filtered, amount_min, amount_max)
    filtered = filter_by_types(filtered, types)
    filtered = filter_by_categories(filtered, categories)
    filtered = filter_by_query(filtered, query)
    return filtered


def build_dashboard_metrics(
    df: pd.DataFrame,
    start: str,
    end: str,
    totals_df: pd.DataFrame | None = None,
    opening_source_df: pd.DataFrame | None = None,
    include_opening_balance: bool = True,
) -> dict:
    """Build dashboard charts and totals with separate display/calculation scopes.

    ``df`` is the visible/chart source. ``totals_df`` is optional and is used
    for money-position cards. This prevents the default Jan-1st display window
    from hiding older rows in the tracked net while still keeping charts compact.

    ``opening_source_df`` is the full-history source used only to calculate the
    opening balance before the visible date window. This is the important part
    for the cumulative balance chart: the chart still shows only the visible
    period, but it starts from the real balance carried forward from older rows
    instead of pretending January 1st was zero.
    """
    totals_source = totals_df if totals_df is not None else df
    totals = summary_totals(totals_source)
    df_month = monthly_summary(df, start=start, end=end)
    df_cat = expenses_by_category(df)
    df_cum = cumulative_balance_with_opening(
        df,
        start=start,
        opening_source_df=opening_source_df,
        include_opening_balance=include_opening_balance,
    )

    plot_monthly_summary(df_month)
    plot_expenses_by_category(df_cat)
    plot_cumulative_balance(df_cum)

    return {
        "totals": totals,
        "monthly_summary": df_month,
        "expenses_by_category": df_cat,
        "cumulative_balance": df_cum,
        "charts": {
            "monthly_summary": chart_monthly_summary(df_month),
            "expenses_by_category": chart_expenses_by_category(df_cat),
            "cumulative_balance": chart_cumulative_balance(df_cum),
        },
    }


def cumulative_balance_with_opening(
    visible_df: pd.DataFrame,
    start: str | None = None,
    opening_source_df: pd.DataFrame | None = None,
    include_opening_balance: bool = True,
) -> pd.DataFrame:
    """Return cumulative balance for visible rows, optionally with carried balance.

    This avoids creating fake year-closing transactions. Older rows stay in the
    background as an initial condition; the chart/table can still show only the
    current year or selected date window.
    """
    if visible_df.empty:
        if include_opening_balance and opening_source_df is not None and start:
            opening_balance = _opening_balance_before(opening_source_df, start)
            if abs(opening_balance) > 1e-9:
                return pd.DataFrame([{
                    "date": pd.to_datetime(start, errors="coerce"),
                    "balance": float(opening_balance),
                }]).dropna(subset=["date"])
        return pd.DataFrame(columns=["date", "balance"])

    df_cum = cumulative_balance(visible_df)
    if not include_opening_balance or opening_source_df is None or not start:
        return df_cum

    opening_balance = _opening_balance_before(opening_source_df, start)
    if abs(opening_balance) <= 1e-9:
        return df_cum

    df_cum = df_cum.copy()
    df_cum["balance"] = pd.to_numeric(df_cum["balance"], errors="coerce").fillna(0.0) + opening_balance

    start_dt = pd.to_datetime(start, errors="coerce")
    if pd.isna(start_dt):
        return df_cum

    first_visible_date = pd.to_datetime(df_cum["date"], errors="coerce").min()
    if pd.isna(first_visible_date) or start_dt <= first_visible_date:
        opening_row = pd.DataFrame([{"date": start_dt, "balance": float(opening_balance)}])
        df_cum = pd.concat([opening_row, df_cum], ignore_index=True, sort=False)

    return df_cum.sort_values("date").reset_index(drop=True)


def _opening_balance_before(df: pd.DataFrame, start: str | None) -> float:
    if df is None or df.empty or not start or "date" not in df.columns or "signed_amount" not in df.columns:
        return 0.0
    start_dt = pd.to_datetime(start, errors="coerce")
    if pd.isna(start_dt):
        return 0.0
    dated = df.copy()
    dated["date"] = pd.to_datetime(dated["date"], errors="coerce")
    dated = dated[dated["date"].notna() & (dated["date"] < start_dt)]
    if dated.empty:
        return 0.0
    return float(pd.to_numeric(dated["signed_amount"], errors="coerce").fillna(0.0).sum())


def build_analysis_metrics(df: pd.DataFrame, period_key: str = "ytd", scope: str = "global") -> dict:
    """Build a decision-oriented professional analysis cockpit.

    The selected period controls the charts and behavioural analysis. The full
    history is still used for the real net balance and opening balance, so the
    page does not confuse a selected date window with your actual money position.
    """
    selected_scope = scope or "global"
    main_df_all = transactions_for_scope(df, selected_scope)
    period = _resolve_analysis_period(main_df_all, period_key)
    main_df_display = filter_by_date(main_df_all, period["start"], period["end"])
    previous_df = _previous_period_frame(main_df_all, period)

    full_totals = summary_totals(main_df_all)
    period_totals = summary_totals(main_df_display)
    previous_totals = summary_totals(previous_df) if not previous_df.empty else _empty_totals()

    df_wd = weekday_spending(main_df_display)
    df_roll = rolling_net_flow(main_df_display)
    top_expenses = largest_expenses(main_df_display, n=10).copy()
    if not top_expenses.empty:
        top_expenses["date_str"] = top_expenses["date"].dt.strftime("%Y-%m-%d")
        for column in ["description", "category"]:
            if column in top_expenses.columns:
                top_expenses[column] = top_expenses[column].fillna("")

    df_month = monthly_summary(main_df_display, start=period["start"], end=period["end"])
    df_cat = expenses_by_category(main_df_display)
    df_cum = cumulative_balance_with_opening(
        main_df_display,
        start=period["start"],
        opening_source_df=main_df_all,
        include_opening_balance=True,
    )

    habits_month = monthly_summary(main_df_all)
    habits = _spending_habits(main_df_all, habits_month, df_cat, df_wd)
    investment = investment_habit_snapshot(refresh=False)
    recurring_pressure = _recurring_pressure_snapshot(selected_scope)
    liabilities = _liability_snapshot(selected_scope)
    from money_manager.services.account_scope_service import all_financial_center_summaries, scope_balance_summary
    scope_summary = scope_balance_summary(selected_scope)
    financial_center_breakdown = all_financial_center_summaries() if selected_scope == "global" else []
    income_sources = _income_sources(main_df_display)
    category_rows = _category_rows(df_cat, previous_df)
    cashflow_statement = _cashflow_statement(period_totals)
    comparison = _comparison_snapshot(period_totals, previous_totals)
    health = _financial_health_score(
        full_totals=full_totals,
        period_totals=period_totals,
        habits=habits,
        recurring_pressure=recurring_pressure,
        liabilities=liabilities,
    )
    insight_cards = _insight_cards(period_totals, habits, investment)
    action_items = _action_items(
        health=health,
        habits=habits,
        liabilities=liabilities,
        recurring_pressure=recurring_pressure,
        category_rows=category_rows,
        comparison=comparison,
    )

    plot_monthly_summary(df_month)
    plot_expenses_by_category(df_cat)
    plot_cumulative_balance(df_cum)
    plot_weekday_spending(df_wd)
    plot_rolling_net_flow(df_roll)

    return {
        "period": period,
        "period_options": _period_options_with_active(period["key"]),
        "totals": full_totals,  # backwards compatible with older template snippets
        "full_totals": full_totals,
        "period_totals": period_totals,
        "previous_totals": previous_totals,
        "comparison": comparison,
        "health": health,
        "habits": habits,
        "investment": investment,
        "recurring_pressure": recurring_pressure,
        "liabilities": liabilities,
        "income_sources": income_sources,
        "category_rows": category_rows,
        "cashflow_statement": cashflow_statement,
        "insight_cards": insight_cards,
        "action_items": action_items,
        "scope_summary": scope_summary,
        "financial_center_breakdown": financial_center_breakdown,
        "weekday_data": df_wd.to_dict(orient="records"),
        "top_expenses": top_expenses.to_dict(orient="records"),
        "selected_scope": selected_scope,
        "charts": {
            "cashflow_waterfall": chart_cashflow_waterfall(cashflow_statement),
            "monthly_summary": chart_monthly_summary(df_month),
            "monthly_savings_rate": chart_monthly_savings_rate(df_month),
            "rolling_net_flow": chart_rolling_net_flow(df_roll),
            "expenses_by_category": chart_expenses_by_category(df_cat),
            "spending_pareto": chart_spending_pareto(df_cat),
            "income_sources": chart_income_sources(income_sources),
            "weekday_spending": chart_weekday_spending(df_wd),
            "cumulative_balance": chart_cumulative_balance(df_cum),
            "investment_cashflows": investment["cashflows_chart"],
        },
    }


def build_analysis_metrics_cached(period_key: str = "ytd", scope: str = "global") -> dict:
    from money_manager.services.calculation_service import cached_context
    from money_manager.services.transaction_service import load_transactions

    return cached_context(
        "analysis_metrics",
        lambda: build_analysis_metrics(load_transactions(), period_key=period_key, scope=scope),
        params={"period": period_key, "scope": str(scope or "global")},
    )


def period_summaries(df: pd.DataFrame) -> tuple[dict, dict]:
    today = pd.Timestamp.today()
    start_this_month = today.replace(day=1)
    start_3_months = today - pd.DateOffset(months=3)

    df_this_month = df[(df["date"] >= start_this_month) & (df["date"] <= today)]
    df_3_months = df[(df["date"] >= start_3_months) & (df["date"] <= today)]

    return period_income_expense(df_this_month), period_income_expense(df_3_months)


def _resolve_analysis_period(main_df_all: pd.DataFrame, period_key: str) -> dict:
    key = (period_key or "ytd").strip().lower()
    valid_keys = {option["key"] for option in PERIOD_OPTIONS}
    if key not in valid_keys:
        key = "ytd"

    today = pd.Timestamp.today().normalize()
    if key == "all":
        if main_df_all.empty or "date" not in main_df_all.columns:
            start = today.replace(day=1)
        else:
            valid_dates = pd.to_datetime(main_df_all["date"], errors="coerce").dropna()
            start = valid_dates.min().normalize() if not valid_dates.empty else today.replace(day=1)
        end = today
    elif key == "last_365":
        start, end = today - pd.Timedelta(days=364), today
    elif key == "last_180":
        start, end = today - pd.Timedelta(days=179), today
    elif key == "last_90":
        start, end = today - pd.Timedelta(days=89), today
    else:
        start_default, end_default = default_date_range()
        start = pd.to_datetime(start_default, errors="coerce")
        end = pd.to_datetime(end_default, errors="coerce")
        if pd.isna(start):
            start = today.replace(month=1, day=1)
        if pd.isna(end):
            end = today

    days = max(1, int((end - start).days) + 1) if not pd.isna(start) and not pd.isna(end) else 1
    return {
        "key": key,
        "start": start.strftime("%Y-%m-%d"),
        "end": end.strftime("%Y-%m-%d"),
        "days": days,
        "label": _period_label(key, start, end),
    }


def _period_label(key: str, start: pd.Timestamp, end: pd.Timestamp) -> str:
    if key == "ytd":
        return f"{end.year} year to date"
    if key == "last_90":
        return "last 90 days"
    if key == "last_180":
        return "last 6 months"
    if key == "last_365":
        return "last 12 months"
    return "all available history"


def _period_options_with_active(active_key: str) -> list[dict]:
    options = []
    for option in PERIOD_OPTIONS:
        item = dict(option)
        item["active"] = item["key"] == active_key
        options.append(item)
    return options


def _previous_period_frame(df: pd.DataFrame, period: dict) -> pd.DataFrame:
    if df.empty or period.get("key") == "all":
        return df.iloc[0:0].copy()
    start = pd.to_datetime(period.get("start"), errors="coerce")
    if pd.isna(start):
        return df.iloc[0:0].copy()
    days = int(period.get("days") or 1)
    prev_end = start - pd.Timedelta(days=1)
    prev_start = prev_end - pd.Timedelta(days=max(0, days - 1))
    return filter_by_date(df, prev_start.strftime("%Y-%m-%d"), prev_end.strftime("%Y-%m-%d"))


def _empty_totals() -> dict:
    return {
        "income": 0.0,
        "expenses": 0.0,
        "investments": 0.0,
        "net": 0.0,
        "savings_rate": 0.0,
        "total_availability": 0.0,
    }


def _spending_habits(main_df: pd.DataFrame, df_month: pd.DataFrame, df_cat: pd.DataFrame, df_wd: pd.DataFrame) -> dict:
    recent = _recent_months(df_month, months=6)
    complete = recent.copy()
    if not complete.empty:
        # Keep the current month if it is the only available month, otherwise
        # drop it because it may be incomplete and misleading.
        current_month = pd.Timestamp.today().to_period("M").strftime("%Y-%m")
        if len(complete) > 1:
            complete = complete[complete["month"].astype(str) != current_month]
        if complete.empty:
            complete = recent

    smart_habits = estimate_cashflow_habits(main_df, df_month)
    avg_income = float(smart_habits["income"]["value"])
    avg_expenses = float(smart_habits["spending"]["value"])
    avg_investments = _mean_nonempty(complete, "investments")
    avg_net = float(smart_habits["monthly_net"])
    savings_rate = 0.0 if avg_income <= 0 else max(avg_net, 0.0) / avg_income * 100.0
    burn_ratio = float(smart_habits["burn_ratio"])

    latest_month = complete.tail(1).to_dict(orient="records")
    latest_month = latest_month[0] if latest_month else {"month": "", "income": 0.0, "expenses": 0.0, "investments": 0.0, "net": 0.0}

    top_category = {"category": "No expenses yet", "total": 0.0, "share_pct": 0.0}
    if not df_cat.empty:
        total_expenses = float(df_cat["total"].sum() or 0.0)
        top = df_cat.iloc[0].to_dict()
        top_category = {
            "category": top.get("category", "Uncategorized"),
            "total": float(top.get("total", 0.0) or 0.0),
            "share_pct": 0.0 if total_expenses <= 0 else float(top.get("total", 0.0) or 0.0) / total_expenses * 100.0,
        }

    peak_weekday = {"weekday": "No pattern yet", "total": 0.0}
    if not df_wd.empty:
        peak_weekday = df_wd.sort_values("total", ascending=False).iloc[0].to_dict()
        peak_weekday["total"] = float(peak_weekday.get("total", 0.0) or 0.0)

    return {
        "months_used": int(len(complete)),
        "avg_monthly_income": float(avg_income),
        "avg_monthly_expenses": float(avg_expenses),
        "avg_monthly_investments": float(avg_investments),
        "avg_monthly_net": float(avg_net),
        "savings_rate": float(savings_rate),
        "burn_ratio": float(burn_ratio),
        "latest_month": latest_month,
        "top_category": top_category,
        "peak_weekday": peak_weekday,
        "income_method": smart_habits["income"].get("method", "smart income habit"),
        "spending_method": smart_habits["spending"].get("method", "smart spending habit"),
        "income_one_offs_excluded": smart_habits["income"].get("excluded_one_offs", 0),
        "spending_one_offs_excluded": smart_habits["spending"].get("excluded_one_offs", 0),
    }


def _recent_months(df_month: pd.DataFrame, months: int = 6) -> pd.DataFrame:
    if df_month.empty:
        return pd.DataFrame(columns=["month", "income", "expenses", "investments", "net"])
    tmp = df_month.copy()
    tmp["month_dt"] = pd.to_datetime(tmp["month"].astype(str) + "-01", errors="coerce")
    tmp = tmp.dropna(subset=["month_dt"]).sort_values("month_dt")
    return tmp.tail(months).drop(columns=["month_dt"])


def _mean_nonempty(df: pd.DataFrame, column: str) -> float:
    if df.empty or column not in df:
        return 0.0
    return float(pd.to_numeric(df[column], errors="coerce").fillna(0.0).mean())


def _comparison_snapshot(current: dict, previous: dict) -> dict:
    return {
        "income_delta": float(current.get("income", 0.0) - previous.get("income", 0.0)),
        "income_delta_pct": _pct_delta(current.get("income", 0.0), previous.get("income", 0.0)),
        "expense_delta": float(current.get("expenses", 0.0) - previous.get("expenses", 0.0)),
        "expense_delta_pct": _pct_delta(current.get("expenses", 0.0), previous.get("expenses", 0.0)),
        "net_delta": float(current.get("net", 0.0) - previous.get("net", 0.0)),
        "savings_rate_delta": float(current.get("savings_rate", 0.0) - previous.get("savings_rate", 0.0)),
        "has_previous": abs(previous.get("income", 0.0)) > 1e-9 or abs(previous.get("expenses", 0.0)) > 1e-9 or abs(previous.get("net", 0.0)) > 1e-9,
    }


def _pct_delta(current: float, previous: float) -> float:
    previous = float(previous or 0.0)
    current = float(current or 0.0)
    if abs(previous) <= 1e-9:
        return 0.0
    return (current - previous) / abs(previous) * 100.0


def _cashflow_statement(totals: dict) -> dict:
    income = float(totals.get("income", 0.0) or 0.0)
    expenses = float(totals.get("expenses", 0.0) or 0.0)
    investments = float(totals.get("investments", 0.0) or 0.0)
    net = float(totals.get("net", 0.0) or 0.0)
    return {
        "income": income,
        "expenses": expenses,
        "investments": investments,
        "net": net,
        "cash_after_expenses": income - expenses,
        "spending_ratio": 0.0 if income <= 0 else expenses / income * 100.0,
        "investment_ratio": 0.0 if income <= 0 else investments / income * 100.0,
        "leftover_ratio": 0.0 if income <= 0 else net / income * 100.0,
    }


def _income_sources(df: pd.DataFrame) -> list[dict]:
    if df.empty or "type" not in df.columns:
        return []
    income = df[df["type"] == "income"].copy()
    if income.empty:
        return []
    income["source"] = income.get("category", "").fillna("").astype(str).str.strip().replace("", "Uncategorised income")
    grouped = income.groupby("source")["signed_amount"].sum().reset_index()
    grouped = grouped.rename(columns={"signed_amount": "total"}).sort_values("total", ascending=False)
    total = float(grouped["total"].sum() or 0.0)
    grouped["share_pct"] = grouped["total"].map(lambda value: 0.0 if total <= 0 else float(value) / total * 100.0)
    return grouped.head(8).to_dict(orient="records")


def _category_rows(df_cat: pd.DataFrame, previous_df: pd.DataFrame) -> list[dict]:
    if df_cat.empty:
        return []
    previous_cat = expenses_by_category(previous_df) if previous_df is not None and not previous_df.empty else pd.DataFrame(columns=["category", "total"])
    previous_lookup = {str(row.get("category", "")): float(row.get("total", 0.0) or 0.0) for row in previous_cat.to_dict(orient="records")}
    total = float(df_cat["total"].sum() or 0.0)
    rows = []
    for item in df_cat.head(8).to_dict(orient="records"):
        category = str(item.get("category", "Uncategorised") or "Uncategorised")
        amount = float(item.get("total", 0.0) or 0.0)
        previous = previous_lookup.get(category, 0.0)
        rows.append({
            "category": category,
            "total": amount,
            "share_pct": 0.0 if total <= 0 else amount / total * 100.0,
            "previous_total": previous,
            "delta": amount - previous,
            "delta_pct": _pct_delta(amount, previous),
        })
    return rows


def _recurring_pressure_snapshot(scope: str = "global") -> dict:
    today = date.today()
    rows = []
    monthly_expense = 0.0
    monthly_income = 0.0
    monthly_investment = 0.0
    active_count = 0
    try:
        from money_manager.services.account_scope_service import recurring_for_scope
        source_rows = recurring_for_scope(scope)
    except Exception:
        source_rows = load_recurring()
    for row in source_rows:
        if not _recurring_is_active(row, today):
            continue
        amount = _safe_amount(row.get("amount"))
        frequency = max(1, int(_safe_amount(row.get("frequency")) or 1))
        monthly = amount / frequency
        tx_type = str(row.get("type") or "expense").strip().lower()
        active_count += 1
        if tx_type == "income":
            monthly_income += monthly
        elif tx_type == "investment":
            monthly_investment += monthly
        else:
            monthly_expense += monthly
        rows.append({
            "name": row.get("name") or row.get("category") or "Recurring rule",
            "type": tx_type,
            "category": row.get("category") or "",
            "amount": amount,
            "frequency": frequency,
            "monthly_equivalent": monthly,
        })
    rows = sorted(rows, key=lambda item: item["monthly_equivalent"], reverse=True)
    return {
        "monthly_expense": float(monthly_expense),
        "monthly_income": float(monthly_income),
        "monthly_investment": float(monthly_investment),
        "monthly_total_outflow": float(monthly_expense + monthly_investment),
        "net_monthly_commitment": float(monthly_income - monthly_expense - monthly_investment),
        "active_count": int(active_count),
        "top_rules": rows[:6],
    }


def _recurring_is_active(row: dict, today: date) -> bool:
    end = _safe_date(row.get("end_date"))
    if end and end < today:
        return False
    start = _safe_date(row.get("start_date"))
    if start and start > today:
        # Show future commitments only if they start within the next 45 days.
        return (start - today).days <= 45
    return True


def _liability_snapshot(scope: str = "global") -> dict:
    today = date.today()
    due_limit = today + timedelta(days=30)

    try:
        from money_manager.services.account_scope_service import debts_for_scope, payables_for_scope, pending_for_scope, receivables_for_scope
        debt_rows = debts_for_scope(scope)
        payable_rows = payables_for_scope(scope)
        receivable_rows = receivables_for_scope(scope)
        pending_rows = pending_for_scope(scope)
    except Exception:
        debt_rows = load_debts()
        payable_rows = load_payables()
        receivable_rows = load_receivables()
        pending_rows = load_pending()

    debts = [_normalize_money_row(row, label_key="creditor") for row in debt_rows]
    payables = [_normalize_money_row(row, label_key="payee") for row in payable_rows]
    receivables = [_normalize_money_row(row, label_key="debtor") for row in receivable_rows]
    pending = [_normalize_pending_row(row) for row in pending_rows]

    active_debts = [row for row in debts if row["active"]]
    active_payables = [row for row in payables if row["active"]]
    active_receivables = [row for row in receivables if row["active"]]
    pending_open = [row for row in pending if row["active"]]

    due_30 = 0.0
    for row in [*active_debts, *active_payables, *pending_open]:
        due = row.get("due_date")
        if due and today <= due <= due_limit:
            due_30 += row["remaining"]

    debts_total = sum(row["remaining"] for row in active_debts)
    payables_total = sum(row["remaining"] for row in active_payables)
    pending_total = sum(row["remaining"] for row in pending_open)
    receivables_total = sum(row["remaining"] for row in active_receivables)
    net_obligations = debts_total + payables_total + pending_total - receivables_total

    return {
        "debts_total": float(debts_total),
        "payables_total": float(payables_total),
        "pending_total": float(pending_total),
        "receivables_total": float(receivables_total),
        "net_obligations": float(net_obligations),
        "due_30": float(due_30),
        "active_debts": len(active_debts),
        "active_payables": len(active_payables),
        "active_pending": len(pending_open),
        "active_receivables": len(active_receivables),
        "largest_obligations": sorted([*active_debts, *active_payables, *pending_open], key=lambda row: row["remaining"], reverse=True)[:6],
        "largest_receivables": sorted(active_receivables, key=lambda row: row["remaining"], reverse=True)[:4],
    }


def _normalize_money_row(row: dict, label_key: str) -> dict:
    remaining = _safe_amount(row.get("remaining_amount"))
    original = _safe_amount(row.get("original_amount"))
    status = str(row.get("status") or "").strip().lower()
    due = _safe_date(row.get("due_date"))
    return {
        "name": row.get("name") or row.get(label_key) or "Item",
        "person": row.get(label_key) or "",
        "remaining": remaining,
        "original": original,
        "status": status,
        "active": status in {"", "active", "pending"} and remaining > 0.005,
        "due_date": due,
        "due_date_str": due.isoformat() if due else "",
    }


def _normalize_pending_row(row: dict) -> dict:
    due = _safe_date(row.get("date_due"))
    status = str(row.get("status") or "").strip().lower()
    return {
        "name": row.get("description") or row.get("category") or "Pending payment",
        "person": row.get("account") or "",
        "remaining": _safe_amount(row.get("amount")),
        "original": _safe_amount(row.get("amount")),
        "status": status,
        "active": status in {"", "pending"},
        "due_date": due,
        "due_date_str": due.isoformat() if due else "",
    }


def _safe_date(value) -> date | None:
    if not value:
        return None
    try:
        parsed = pd.to_datetime(value, errors="coerce")
    except Exception:
        return None
    if pd.isna(parsed):
        return None
    return parsed.date()


def _safe_amount(value) -> float:
    try:
        number = float(str(value or 0).replace(",", "."))
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(number) or math.isinf(number):
        return 0.0
    return float(number)


def _financial_health_score(full_totals: dict, period_totals: dict, habits: dict, recurring_pressure: dict, liabilities: dict) -> dict:
    score = 70.0
    avg_income = float(habits.get("avg_monthly_income", 0.0) or 0.0)
    avg_expenses = float(habits.get("avg_monthly_expenses", 0.0) or 0.0)
    avg_net = float(habits.get("avg_monthly_net", 0.0) or 0.0)
    burn_ratio = float(habits.get("burn_ratio", 0.0) or 0.0)
    real_net = float(full_totals.get("net", 0.0) or 0.0)
    net_obligations = float(liabilities.get("net_obligations", 0.0) or 0.0)
    recurring_out = float(recurring_pressure.get("monthly_total_outflow", 0.0) or 0.0)
    recurring_ratio = 0.0 if avg_income <= 0 else recurring_out / avg_income * 100.0
    runway_months = 99.0 if avg_expenses <= 0 else max(real_net, 0.0) / avg_expenses

    if avg_net >= 0:
        score += 12
    else:
        score -= 22

    if burn_ratio > 95:
        score -= 18
    elif burn_ratio > 80:
        score -= 10
    elif burn_ratio < 60 and avg_income > 0:
        score += 8

    if recurring_ratio > 45:
        score -= 12
    elif recurring_ratio > 30:
        score -= 7
    elif recurring_ratio < 15 and recurring_out > 0:
        score += 4

    if runway_months < 1:
        score -= 15
    elif runway_months < 2:
        score -= 8
    elif runway_months >= 4:
        score += 10

    if net_obligations > max(real_net, 1.0):
        score -= 12
    elif net_obligations <= 0:
        score += 6

    if float(period_totals.get("net", 0.0) or 0.0) >= 0:
        score += 4
    else:
        score -= 6

    score = int(round(max(0, min(100, score))))
    if score >= 82:
        label = "Strong"
        tone = "good"
        text = "The page is showing a healthy cashflow structure. Keep protecting the margin."
    elif score >= 65:
        label = "Stable"
        tone = "neutral"
        text = "The situation is controlled, but there are clear areas to optimise."
    elif score >= 45:
        label = "Watch"
        tone = "warning"
        text = "There is pressure in the system. Focus on obligations and recurring leakage first."
    else:
        label = "Risky"
        tone = "danger"
        text = "Your liquidity is too exposed. This needs active correction, not just tracking."

    return {
        "score": score,
        "label": label,
        "tone": tone,
        "text": text,
        "runway_months": float(runway_months),
        "recurring_ratio": float(recurring_ratio),
        "net_obligations": float(net_obligations),
    }


def _action_items(health: dict, habits: dict, liabilities: dict, recurring_pressure: dict, category_rows: list[dict], comparison: dict) -> list[dict]:
    items = []

    if category_rows:
        top = category_rows[0]
        items.append({
            "priority": "High" if top["share_pct"] >= 35 else "Medium",
            "title": f"Review {top['category']}",
            "text": f"This category is €{top['total']:.2f}, equal to {top['share_pct']:.0f}% of period expenses.",
            "metric": f"€{top['total']:.2f}",
        })

    if recurring_pressure.get("monthly_total_outflow", 0.0) > 0:
        items.append({
            "priority": "High" if health.get("recurring_ratio", 0.0) >= 30 else "Medium",
            "title": "Audit fixed monthly commitments",
            "text": f"Recurring expenses and investments reserve about {health.get('recurring_ratio', 0.0):.0f}% of the estimated monthly income habit.",
            "metric": f"€{recurring_pressure['monthly_total_outflow']:.2f}/mo",
        })

    if liabilities.get("due_30", 0.0) > 0:
        items.append({
            "priority": "High",
            "title": "Prepare the next 30 days",
            "text": "Upcoming due payments should be covered before discretionary expenses.",
            "metric": f"€{liabilities['due_30']:.2f}",
        })

    if liabilities.get("receivables_total", 0.0) > 0:
        items.append({
            "priority": "Easy win",
            "title": "Collect recoverable money",
            "text": "Receivables improve liquidity without cutting your lifestyle.",
            "metric": f"€{liabilities['receivables_total']:.2f}",
        })

    if comparison.get("has_previous") and comparison.get("expense_delta_pct", 0.0) > 15:
        items.append({
            "priority": "Medium",
            "title": "Spending accelerated vs previous period",
            "text": f"Expenses are up {comparison['expense_delta_pct']:.0f}% compared with the previous comparable window.",
            "metric": f"+€{comparison['expense_delta']:.2f}",
        })

    if not items:
        items.append({
            "priority": "Good",
            "title": "Keep tracking consistently",
            "text": "No major pressure point stands out yet. More logged months will make the analysis sharper.",
            "metric": "OK",
        })

    return items[:5]


def _insight_cards(totals: dict, habits: dict, investment: dict) -> list[dict]:
    cards = []

    burn_ratio = habits["burn_ratio"]
    if burn_ratio >= 90:
        cards.append({
            "label": "Spending pressure",
            "value": f"{burn_ratio:.0f}%",
            "tone": "danger",
            "text": "Expenses are eating almost all monthly income. This is where I would tighten first.",
        })
    elif burn_ratio >= 70:
        cards.append({
            "label": "Spending pressure",
            "value": f"{burn_ratio:.0f}%",
            "tone": "warning",
            "text": "Spending is manageable, but there is not a huge margin if income is delayed.",
        })
    else:
        cards.append({
            "label": "Spending pressure",
            "value": f"{burn_ratio:.0f}%",
            "tone": "good",
            "text": "Expenses are staying comfortably below average income.",
        })

    cards.append({
        "label": "Average monthly net",
        "value": f"€{habits['avg_monthly_net']:.2f}",
        "tone": "good" if habits["avg_monthly_net"] >= 0 else "danger",
        "text": "Smart estimate based on recent frequency and cleaned one-off activity.",
    })

    cards.append({
        "label": "Top spending area",
        "value": habits["top_category"]["category"],
        "tone": "neutral",
        "text": f"€{habits['top_category']['total']:.2f}, about {habits['top_category']['share_pct']:.0f}% of categorised expenses.",
    })

    cards.append({
        "label": "Investment habit",
        "value": f"€{investment['monthly_net_investment']:.2f}/mo",
        "tone": "good" if investment["monthly_net_investment"] >= 0 else "warning",
        "text": "Latest repeated deposits/buys minus withdrawals/sells. Old one-off top-ups are downweighted.",
    })

    cards.append({
        "label": "Market P/L",
        "value": f"€{investment['profit_loss']:.2f}",
        "tone": "good" if investment["profit_loss"] >= 0 else "danger",
        "text": f"Estimated from the same proxy used in the Investments page: {investment['profit_loss_pct']:.2f}% total move.",
    })

    return cards
