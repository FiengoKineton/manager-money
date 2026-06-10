from __future__ import annotations

import pandas as pd

from money_manager.services.account_service import main_account_transactions
from money_manager.services.investment_service import investment_habit_snapshot
from money_manager.utils.filters import filter_by_amount_range, filter_by_categories, filter_by_date, filter_by_query, filter_by_types
from money_manager.utils.interactive_plots import (
    chart_cumulative_balance,
    chart_expenses_by_category,
    chart_monthly_summary,
    chart_rolling_net_flow,
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


def apply_transaction_filters(df: pd.DataFrame, start, end, types, categories, query, amount_min=None, amount_max=None) -> pd.DataFrame:
    filtered = df.copy()
    filtered = filter_by_date(filtered, start, end)
    filtered = filter_by_amount_range(filtered, amount_min, amount_max)
    filtered = filter_by_types(filtered, types)
    filtered = filter_by_categories(filtered, categories)
    filtered = filter_by_query(filtered, query)
    return filtered


def build_dashboard_metrics(df: pd.DataFrame, start: str, end: str) -> dict:
    totals = summary_totals(df)
    df_month = monthly_summary(df, start=start, end=end)
    df_cat = expenses_by_category(df)
    df_cum = cumulative_balance(df)

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


def build_analysis_metrics(df: pd.DataFrame) -> dict:
    """Build a richer, decision-oriented analysis page.

    Main-bank transactions are still the base for spending/income habits because
    they represent the conservative daily money flow. Investment behaviour is
    analysed separately and merged into the page so the analysis does not mix
    normal expenses with portfolio operations.
    """
    main_df = main_account_transactions(df)
    totals = summary_totals(main_df)
    df_wd = weekday_spending(main_df)
    df_roll = rolling_net_flow(main_df)
    top_expenses = largest_expenses(main_df, n=10).copy()

    if not top_expenses.empty:
        top_expenses["date_str"] = top_expenses["date"].dt.strftime("%Y-%m-%d")
        for column in ["description", "category"]:
            if column in top_expenses.columns:
                top_expenses[column] = top_expenses[column].fillna("")

    df_month = monthly_summary(main_df)
    df_cat = expenses_by_category(main_df)
    df_cum = cumulative_balance(main_df)
    habits = _spending_habits(main_df, df_month, df_cat, df_wd)
    investment = investment_habit_snapshot(refresh=False)
    insight_cards = _insight_cards(totals, habits, investment)

    plot_monthly_summary(df_month)
    plot_expenses_by_category(df_cat)
    plot_cumulative_balance(df_cum)
    plot_weekday_spending(df_wd)
    plot_rolling_net_flow(df_roll)

    return {
        "totals": totals,
        "habits": habits,
        "investment": investment,
        "insight_cards": insight_cards,
        "weekday_data": df_wd.to_dict(orient="records"),
        "top_expenses": top_expenses.to_dict(orient="records"),
        "charts": {
            "monthly_summary": chart_monthly_summary(df_month),
            "rolling_net_flow": chart_rolling_net_flow(df_roll),
            "expenses_by_category": chart_expenses_by_category(df_cat),
            "weekday_spending": chart_weekday_spending(df_wd),
            "cumulative_balance": chart_cumulative_balance(df_cum),
            "investment_cashflows": investment["cashflows_chart"],
        },
    }


def period_summaries(df: pd.DataFrame) -> tuple[dict, dict]:
    today = pd.Timestamp.today()
    start_this_month = today.replace(day=1)
    start_3_months = today - pd.DateOffset(months=3)

    df_this_month = df[(df["date"] >= start_this_month) & (df["date"] <= today)]
    df_3_months = df[(df["date"] >= start_3_months) & (df["date"] <= today)]

    return period_income_expense(df_this_month), period_income_expense(df_3_months)


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

    avg_income = _mean_nonempty(complete, "income")
    avg_expenses = _mean_nonempty(complete, "expenses")
    avg_investments = _mean_nonempty(complete, "investments")
    avg_net = _mean_nonempty(complete, "net")
    savings_rate = 0.0 if avg_income <= 0 else max(avg_net, 0.0) / avg_income * 100.0
    burn_ratio = 0.0 if avg_income <= 0 else avg_expenses / avg_income * 100.0

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
        "text": f"Based on the last {habits['months_used']} usable month(s) of main-bank activity.",
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
        "text": "Average deposits/buys minus withdrawals/sells. Dividends are tracked separately.",
    })

    cards.append({
        "label": "Market P/L",
        "value": f"€{investment['profit_loss']:.2f}",
        "tone": "good" if investment["profit_loss"] >= 0 else "danger",
        "text": f"Estimated from the same proxy used in the Investments page: {investment['profit_loss_pct']:.2f}% total move.",
    })

    return cards
