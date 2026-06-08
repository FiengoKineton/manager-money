import pandas as pd

from money_manager.utils.filters import filter_by_categories, filter_by_date, filter_by_query, filter_by_types
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


def apply_transaction_filters(df: pd.DataFrame, start, end, types, categories, query) -> pd.DataFrame:
    filtered = df.copy()
    filtered = filter_by_date(filtered, start, end)
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
    totals = summary_totals(df)
    df_wd = weekday_spending(df)
    df_roll = rolling_net_flow(df)
    top_expenses = largest_expenses(df, n=10).copy()

    if not top_expenses.empty:
        top_expenses["date_str"] = top_expenses["date"].dt.strftime("%Y-%m-%d")
        for column in ["description", "category"]:
            if column in top_expenses.columns:
                top_expenses[column] = top_expenses[column].fillna("")

    df_month = monthly_summary(df)
    df_cat = expenses_by_category(df)
    df_cum = cumulative_balance(df)

    plot_monthly_summary(df_month)
    plot_expenses_by_category(df_cat)
    plot_cumulative_balance(df_cum)
    plot_weekday_spending(df_wd)
    plot_rolling_net_flow(df_roll)

    return {
        "totals": totals,
        "weekday_data": df_wd.to_dict(orient="records"),
        "top_expenses": top_expenses.to_dict(orient="records"),
        "charts": {
            "monthly_summary": chart_monthly_summary(df_month),
            "rolling_net_flow": chart_rolling_net_flow(df_roll),
            "expenses_by_category": chart_expenses_by_category(df_cat),
            "weekday_spending": chart_weekday_spending(df_wd),
            "cumulative_balance": chart_cumulative_balance(df_cum),
        },
    }


def period_summaries(df: pd.DataFrame) -> tuple[dict, dict]:
    today = pd.Timestamp.today()
    start_this_month = today.replace(day=1)
    start_3_months = today - pd.DateOffset(months=3)

    df_this_month = df[(df["date"] >= start_this_month) & (df["date"] <= today)]
    df_3_months = df[(df["date"] >= start_3_months) & (df["date"] <= today)]

    return period_income_expense(df_this_month), period_income_expense(df_3_months)
