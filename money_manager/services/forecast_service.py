from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

import pandas as pd
import plotly.graph_objects as go

from money_manager.repositories.transactions import load_all
from money_manager.services.account_service import auxiliary_total, main_account_transactions
from money_manager.services.investment_service import investment_habit_snapshot, overview_snapshot
from money_manager.utils.stats import monthly_summary, summary_totals

PLOT_CONFIG = {"displaylogo": False, "responsive": True, "modeBarButtonsToRemove": ["lasso2d", "select2d"]}
BLUE = "#2454d6"
GREEN = "#18794e"
RED = "#c2410c"
INK = "#111827"
MUTED = "#64748b"

INCOME_ONE_OFF_KEYWORDS = {
    "refund",
    "rimborso",
    "reimbursement",
    "initial",
    "initial net",
    "cash",
    "loan",
    "prestito",
    "recovery",
    "recupero",
    "transfer",
    "bonifico giroconto",
}

SPENDING_ONE_OFF_KEYWORDS = {
    "loan",
    "prestito",
    "deposito",
    "deposit",
    "giroconto",
    "transfer",
}


@dataclass
class ForecastParams:
    years: int
    monthly_income: float
    monthly_spending: float
    monthly_net_investment: float
    annual_return_pct: float
    annual_income_growth_pct: float
    annual_spending_growth_pct: float
    starting_cash: float
    starting_investment_value: float
    starting_invested_capital: float
    monthly_dividends: float


def build_forecast_page_context(form=None) -> dict:
    defaults = build_forecast_defaults()
    result = None
    params = defaults["params"]

    if form is not None:
        params = _params_from_form(form, defaults["params"])
        result = project_financial_future(params)

    return {
        "defaults": defaults,
        "params": params,
        "result": result,
    }


def estimate_cashflow_habits(main_df: pd.DataFrame, df_month: pd.DataFrame | None = None) -> dict:
    if df_month is None:
        df_month = monthly_summary(main_df)
    income_habit = _estimate_income_habit(main_df, df_month)
    spending_habit = _estimate_spending_habit(main_df, df_month)
    monthly_net = income_habit["value"] - spending_habit["value"]
    burn_ratio = 0.0 if income_habit["value"] <= 0 else spending_habit["value"] / income_habit["value"] * 100.0
    return {
        "income": income_habit,
        "spending": spending_habit,
        "monthly_net": round(monthly_net, 2),
        "burn_ratio": round(burn_ratio, 2),
    }


def build_forecast_defaults() -> dict:
    from money_manager.services.cache_service import cached_calculation

    return cached_calculation("forecast.defaults", _build_forecast_defaults_uncached)


def _build_forecast_defaults_uncached() -> dict:
    """Build smart defaults for the forecast.

    The defaults deliberately avoid a plain historical average.  They combine:
    - recent complete months, so current/incomplete data does not understate the habit;
    - frequency, so repeated monthly behaviour is trusted more than one-off logs;
    - robust clipping, so big refunds/top-ups do not dominate the forecast.
    """
    df = load_all()
    main_df = main_account_transactions(df)
    monthly = monthly_summary(main_df)

    cashflow_habits = estimate_cashflow_habits(main_df, monthly)
    income_habit = cashflow_habits["income"]
    spending_habit = cashflow_habits["spending"]

    totals = summary_totals(main_df)
    cash = _safe_float(totals.get("net", 0.0)) + auxiliary_total(df)
    investment_overview = overview_snapshot(refresh=False)
    investment_habits = investment_habit_snapshot(refresh=False)

    starting_value = _safe_float(investment_overview.get("estimated_value", 0.0))
    starting_capital = _safe_float(investment_overview.get("net_invested", 0.0))
    if abs(starting_value) < 0.01:
        starting_value = starting_capital

    annual_return = _safe_float(investment_habits.get("annual_return_pct", 0.0))
    if abs(annual_return) < 0.01 and abs(_safe_float(investment_habits.get("profit_loss_pct", 0.0))) > 0.01:
        annual_return = _safe_float(investment_habits.get("profit_loss_pct", 0.0))
    if abs(annual_return) < 0.01:
        annual_return = 5.0

    params = ForecastParams(
        years=5,
        monthly_income=income_habit["value"],
        monthly_spending=spending_habit["value"],
        monthly_net_investment=_safe_float(investment_habits.get("monthly_net_investment", 0.0)),
        annual_return_pct=annual_return,
        annual_income_growth_pct=0.0,
        annual_spending_growth_pct=2.0,
        starting_cash=cash,
        starting_investment_value=starting_value,
        starting_invested_capital=starting_capital,
        monthly_dividends=_safe_float(investment_habits.get("monthly_dividends", 0.0)),
    )

    complete_recent = _recent_complete_months(monthly, months=6)

    return {
        "params": params,
        "months_used": int(max(income_habit.get("months_used", 0), spending_habit.get("months_used", 0), len(complete_recent))),
        "income_habit": income_habit,
        "spending_habit": spending_habit,
        "investment_habits": investment_habits,
        "basis": {
            "main_net": _safe_float(totals.get("net", 0.0)),
            "separate_liquid": auxiliary_total(df),
            "starting_cash": cash,
            "starting_investment_value": starting_value,
            "starting_invested_capital": starting_capital,
        },
    }


def project_financial_future(params: ForecastParams) -> dict:
    months = max(1, int(params.years) * 12)
    monthly_return = _monthly_rate(params.annual_return_pct)
    monthly_income_growth = _monthly_rate(params.annual_income_growth_pct)
    monthly_spending_growth = _monthly_rate(params.annual_spending_growth_pct)

    cash = _safe_float(params.starting_cash)
    investment_value = _safe_float(params.starting_investment_value)
    invested_capital = _safe_float(params.starting_invested_capital)
    current_income = _safe_float(params.monthly_income)
    current_spending = _safe_float(params.monthly_spending)
    current_net_investment = _safe_float(params.monthly_net_investment)
    dividends = _safe_float(params.monthly_dividends)

    today = pd.Timestamp.today().normalize()
    rows = []

    for month in range(1, months + 1):
        date = today + pd.DateOffset(months=month)

        investment_market_gain = investment_value * monthly_return
        investment_value += investment_market_gain

        # Positive net investment means cash is moved into investments. Negative
        # means net selling/withdrawal and cash comes back out.
        cash += current_income + dividends - current_spending - current_net_investment
        investment_value += current_net_investment
        invested_capital += current_net_investment

        total_value = cash + investment_value
        investment_pl = investment_value - invested_capital

        rows.append({
            "month": month,
            "date": date,
            "cash": cash,
            "investment_value": investment_value,
            "invested_capital": invested_capital,
            "investment_profit_loss": investment_pl,
            "total_value": total_value,
            "monthly_income": current_income,
            "monthly_spending": current_spending,
            "monthly_net_investment": current_net_investment,
            "monthly_dividends": dividends,
            "market_gain": investment_market_gain,
        })

        current_income *= 1.0 + monthly_income_growth
        current_spending *= 1.0 + monthly_spending_growth

    projection = pd.DataFrame(rows)
    yearly = _yearly_rows(projection)
    charts = {
        "projection": _chart_projection(projection),
        "cashflow": _chart_cashflow_projection(projection),
        "investment_profit": _chart_investment_profit(projection),
    }

    final = projection.iloc[-1].to_dict() if not projection.empty else {
        "cash": params.starting_cash,
        "investment_value": params.starting_investment_value,
        "invested_capital": params.starting_invested_capital,
        "investment_profit_loss": 0.0,
        "total_value": params.starting_cash + params.starting_investment_value,
    }

    return {
        "years": params.years,
        "params": params,
        "final": final,
        "yearly": yearly,
        "charts": charts,
        "warnings": _forecast_warnings(params, final),
    }


def _params_from_form(form, defaults: ForecastParams) -> ForecastParams:
    return ForecastParams(
        years=max(1, int(_float_from_form(form, "years", defaults.years))),
        monthly_income=_float_from_form(form, "monthly_income", defaults.monthly_income),
        monthly_spending=_float_from_form(form, "monthly_spending", defaults.monthly_spending),
        monthly_net_investment=_float_from_form(form, "monthly_net_investment", defaults.monthly_net_investment),
        annual_return_pct=_float_from_form(form, "annual_return_pct", defaults.annual_return_pct),
        annual_income_growth_pct=_float_from_form(form, "annual_income_growth_pct", defaults.annual_income_growth_pct),
        annual_spending_growth_pct=_float_from_form(form, "annual_spending_growth_pct", defaults.annual_spending_growth_pct),
        starting_cash=_float_from_form(form, "starting_cash", defaults.starting_cash),
        starting_investment_value=_float_from_form(form, "starting_investment_value", defaults.starting_investment_value),
        starting_invested_capital=_float_from_form(form, "starting_invested_capital", defaults.starting_invested_capital),
        monthly_dividends=_float_from_form(form, "monthly_dividends", defaults.monthly_dividends),
    )


def _float_from_form(form, key: str, default: float) -> float:
    try:
        return _safe_float(form.get(key, default), default)
    except (TypeError, ValueError):
        return _safe_float(default)


def _safe_float(value, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default or 0.0)
    if not isfinite(number):
        return float(default or 0.0)
    return number


def _estimate_income_habit(main_df: pd.DataFrame, df_month: pd.DataFrame) -> dict:
    income = _clean_habit_transactions(main_df, "income")
    if income.empty:
        series = _recent_complete_months(df_month, months=6).set_index("month").get("income", pd.Series(dtype=float))
        value = _smart_monthly_series_estimate(series, fallback_column="income")
        return {"value": value, "months_used": int(len(series)), "method": "recent weighted income months", "excluded_one_offs": 0}

    income["is_one_off"] = income.apply(_looks_like_income_one_off, axis=1)
    recurring_income = income[~income["is_one_off"]].copy()
    excluded = int(income["is_one_off"].sum())

    if recurring_income.empty:
        recent = _recent_complete_months(df_month, months=6)
        value = _smart_monthly_series_estimate(recent.set_index("month")["income"] if "income" in recent else pd.Series(dtype=float))
        return {"value": value, "months_used": int(len(recent)), "method": "recent weighted income months", "excluded_one_offs": excluded}

    # Estimate each repeated income source separately. This is better than a
    # raw average because one high/low salary month does not rewrite the default.
    source_values = []
    for _, group in recurring_income.groupby("habit_key"):
        months = _monthly_amount_series(group, value_col="amount", include_current=True)
        nonzero_count = int((months.abs() > 0.01).sum())
        if nonzero_count >= 2 or len(group) >= 2:
            source_values.append(_smart_monthly_series_estimate(months))

    if source_values:
        value = sum(source_values)
        method = "recurring income sources with recent-frequency weighting"
        months_used = int(max(1, recurring_income["date"].dt.to_period("M").nunique()))
    else:
        recent = _recent_complete_months(df_month, months=6)
        value = _smart_monthly_series_estimate(recent.set_index("month")["income"] if "income" in recent else pd.Series(dtype=float))
        method = "recent weighted income months"
        months_used = int(len(recent))

    return {
        "value": round(_safe_float(value), 2),
        "months_used": months_used,
        "method": method,
        "excluded_one_offs": excluded,
    }


def _estimate_spending_habit(main_df: pd.DataFrame, df_month: pd.DataFrame) -> dict:
    expenses = _clean_habit_transactions(main_df, "expense")
    if not expenses.empty:
        expenses["is_one_off"] = expenses.apply(_looks_like_spending_one_off, axis=1)
        excluded = int(expenses["is_one_off"].sum())
        expenses = expenses[~expenses["is_one_off"]]
    else:
        excluded = 0

    if not expenses.empty:
        months = _monthly_amount_series(expenses, value_col="amount", include_current=False)
        value = _smart_monthly_series_estimate(months)
        months_used = int(len(months.tail(6)))
        method = "recent spending months with outlier clipping"
    else:
        recent = _recent_complete_months(df_month, months=6)
        value = _smart_monthly_series_estimate(recent.set_index("month")["expenses"] if "expenses" in recent else pd.Series(dtype=float))
        months_used = int(len(recent))
        method = "recent weighted expense months"

    return {
        "value": round(_safe_float(value), 2),
        "months_used": months_used,
        "method": method,
        "excluded_one_offs": excluded,
    }


def _clean_habit_transactions(df: pd.DataFrame, transaction_type: str) -> pd.DataFrame:
    if df.empty or "type" not in df.columns:
        return pd.DataFrame(columns=["date", "amount", "category", "sub_category", "description", "habit_key"])

    tx = df[df["type"].eq(transaction_type)].copy()
    if tx.empty:
        return pd.DataFrame(columns=["date", "amount", "category", "sub_category", "description", "habit_key"])

    tx["date"] = pd.to_datetime(tx["date"], errors="coerce")
    tx["amount"] = pd.to_numeric(tx["amount"], errors="coerce").fillna(0.0).abs()
    for column in ["category", "sub_category", "description"]:
        if column not in tx.columns:
            tx[column] = ""
        tx[column] = tx[column].fillna("").astype(str)
    tx = tx.dropna(subset=["date"])
    tx = tx[tx["amount"] > 0]
    tx["category_clean"] = tx["category"].str.strip().str.casefold()
    tx["sub_category_clean"] = tx["sub_category"].str.strip().str.casefold()
    tx["description_clean"] = tx["description"].str.strip().str.casefold()
    tx["habit_key"] = tx["category_clean"] + "|" + tx["sub_category_clean"]
    return tx


def _looks_like_income_one_off(row) -> bool:
    text = " ".join([
        str(row.get("category_clean", "")),
        str(row.get("sub_category_clean", "")),
        str(row.get("description_clean", "")),
    ])
    return any(keyword in text for keyword in INCOME_ONE_OFF_KEYWORDS)


def _looks_like_spending_one_off(row) -> bool:
    text = " ".join([
        str(row.get("category_clean", "")),
        str(row.get("sub_category_clean", "")),
        str(row.get("description_clean", "")),
    ])
    return any(keyword in text for keyword in SPENDING_ONE_OFF_KEYWORDS)


def _monthly_amount_series(tx: pd.DataFrame, value_col: str = "amount", include_current: bool = False) -> pd.Series:
    if tx.empty or "date" not in tx:
        return pd.Series(dtype=float)

    tmp = tx.copy()
    tmp["date"] = pd.to_datetime(tmp["date"], errors="coerce")
    tmp[value_col] = pd.to_numeric(tmp[value_col], errors="coerce").fillna(0.0)
    tmp = tmp.dropna(subset=["date"])
    if tmp.empty:
        return pd.Series(dtype=float)

    tmp["month"] = tmp["date"].dt.to_period("M")
    start = tmp["month"].min()
    end = max(pd.Timestamp.today().to_period("M"), tmp["month"].max())
    month_index = pd.period_range(start=start, end=end, freq="M")
    series = tmp.groupby("month")[value_col].sum().reindex(month_index, fill_value=0.0)
    series.index = series.index.astype(str)

    current_month = pd.Timestamp.today().to_period("M").strftime("%Y-%m")
    if not include_current and len(series) > 1 and current_month in series.index:
        series = series.drop(index=current_month)
    return series.astype(float)


def _smart_monthly_series_estimate(series: pd.Series, fallback_column: str | None = None) -> float:
    """Frequency-aware monthly estimate.

    It gives priority to the latest repeated behaviour.  For example, if the
    investment history has big initial top-ups but the last months are 150 EUR,
    the estimate becomes about 150 EUR instead of the whole-period average.
    """
    if series is None or len(series) == 0:
        return 0.0

    values = pd.to_numeric(series, errors="coerce").fillna(0.0).astype(float)
    recent = values.tail(6)
    nonzero_recent = recent[recent.abs() > 0.01]
    nonzero_all = values[values.abs() > 0.01]

    if nonzero_recent.empty and nonzero_all.empty:
        return 0.0

    # If the latest 2-3 non-zero months are consistent, trust them first.
    latest_nonzero = nonzero_all.tail(4)
    if len(latest_nonzero) >= 2:
        last2 = latest_nonzero.tail(2)
        if _values_are_close(last2):
            return round(_safe_float(last2.median()), 2)
    if len(latest_nonzero) >= 3:
        last3 = latest_nonzero.tail(3)
        if _values_are_close(last3):
            return round(_safe_float(last3.median()), 2)

    # Otherwise use a recency-weighted clipped mean over recent months. Zeros are
    # kept if the activity is sporadic, which lowers the estimate correctly.
    recent = recent.copy()
    if len(recent) < 3 and len(values) >= 3:
        recent = values.tail(3)

    clipped = _clip_outliers(recent)
    if clipped.empty:
        return 0.0
    weights = pd.Series(range(1, len(clipped) + 1), index=clipped.index, dtype=float)
    estimate = float((clipped * weights).sum() / weights.sum())
    return round(_safe_float(estimate), 2)


def _values_are_close(values: pd.Series, tolerance: float = 0.30) -> bool:
    vals = pd.to_numeric(values, errors="coerce").dropna().abs()
    vals = vals[vals > 0.01]
    if len(vals) < 2:
        return False
    med = float(vals.median())
    if med <= 0:
        return False
    spread = float((vals - med).abs().max() / med)
    return spread <= tolerance


def _clip_outliers(values: pd.Series) -> pd.Series:
    vals = pd.to_numeric(values, errors="coerce").dropna().astype(float)
    if vals.empty:
        return vals
    nonzero = vals[vals.abs() > 0.01]
    if len(nonzero) < 3:
        return vals
    median = float(nonzero.median())
    mad = float((nonzero - median).abs().median())
    if mad <= 0.01:
        upper = median * 1.5 if median >= 0 else median * 0.5
        lower = median * 0.5 if median >= 0 else median * 1.5
    else:
        upper = median + 2.5 * mad
        lower = median - 2.5 * mad
    if median >= 0:
        lower = max(0.0, lower)
    return vals.clip(lower=lower, upper=upper)


def _recent_complete_months(df_month: pd.DataFrame, months: int = 6) -> pd.DataFrame:
    if df_month.empty:
        return pd.DataFrame(columns=["month", "income", "expenses", "investments", "net"])
    tmp = df_month.copy()
    tmp["month_dt"] = pd.to_datetime(tmp["month"].astype(str) + "-01", errors="coerce")
    tmp = tmp.dropna(subset=["month_dt"]).sort_values("month_dt")
    current_month = pd.Timestamp.today().to_period("M").strftime("%Y-%m")
    if len(tmp) > 1:
        tmp = tmp[tmp["month"].astype(str) != current_month]
    return tmp.tail(months).drop(columns=["month_dt"])


def _mean(df: pd.DataFrame, column: str) -> float:
    if df.empty or column not in df:
        return 0.0
    return _safe_float(pd.to_numeric(df[column], errors="coerce").fillna(0.0).mean())


def _monthly_rate(annual_pct: float) -> float:
    annual = max(_safe_float(annual_pct), -99.0) / 100.0
    return (1.0 + annual) ** (1.0 / 12.0) - 1.0


def _yearly_rows(projection: pd.DataFrame) -> list[dict]:
    if projection.empty:
        return []
    tmp = projection.copy()
    tmp["year"] = ((tmp["month"] - 1) // 12) + 1
    rows = []
    for _, row in tmp.groupby("year", as_index=False).tail(1).iterrows():
        rows.append({
            "year": int(row["year"]),
            "cash": float(row["cash"]),
            "investment_value": float(row["investment_value"]),
            "investment_profit_loss": float(row["investment_profit_loss"]),
            "total_value": float(row["total_value"]),
        })
    return rows


def _forecast_warnings(params: ForecastParams, final: dict) -> list[str]:
    warnings = []
    monthly_free_cash = params.monthly_income + params.monthly_dividends - params.monthly_spending - params.monthly_net_investment
    if monthly_free_cash < 0:
        warnings.append("Your default monthly plan consumes more cash than it produces. The forecast still runs, but cash may trend down.")
    if params.annual_return_pct > 15:
        warnings.append("The annual return assumption is high. It is copied from recent market behaviour, not guaranteed future performance.")
    if final.get("cash", 0.0) < 0:
        warnings.append("Projected cash becomes negative by the end of the horizon. Reduce spending or investment contributions in this scenario.")
    return warnings

def _chart_projection(df: pd.DataFrame) -> str:
    if df.empty:
        return _empty_chart("Forecast")
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df["date"], y=df["total_value"], name="Total projected position", mode="lines", line=dict(color=BLUE, width=4)))
    fig.add_trace(go.Scatter(x=df["date"], y=df["cash"], name="Cash / liquidity", mode="lines", line=dict(color=GREEN, width=3)))
    fig.add_trace(go.Scatter(x=df["date"], y=df["investment_value"], name="Investment value", mode="lines", line=dict(color=INK, width=3)))
    fig.update_layout(title="Projected cash + investments", height=430, yaxis_title="Euro", legend=dict(orientation="h", y=1.08))
    return _to_html(fig)


def _chart_cashflow_projection(df: pd.DataFrame) -> str:
    if df.empty:
        return _empty_chart("Monthly cash-flow assumptions")
    fig = go.Figure()
    fig.add_trace(go.Bar(x=df["date"], y=df["monthly_income"], name="Income", marker_color=GREEN))
    fig.add_trace(go.Bar(x=df["date"], y=-df["monthly_spending"], name="Spending", marker_color=RED))
    fig.add_trace(go.Bar(x=df["date"], y=-df["monthly_net_investment"], name="Net investment cash flow", marker_color=BLUE))
    if df["monthly_dividends"].abs().sum() > 0:
        fig.add_trace(go.Bar(x=df["date"], y=df["monthly_dividends"], name="Dividends", marker_color=MUTED))
    fig.update_layout(title="Projected monthly cash movement", height=360, yaxis_title="Euro", barmode="relative", legend=dict(orientation="h", y=1.08))
    return _to_html(fig)


def _chart_investment_profit(df: pd.DataFrame) -> str:
    if df.empty:
        return _empty_chart("Investment profit/loss forecast")
    colors = [GREEN if value >= 0 else RED for value in df["investment_profit_loss"]]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=df["date"], y=df["investment_profit_loss"], name="Estimated investment P/L", marker_color=colors, opacity=0.55))
    fig.add_trace(go.Scatter(x=df["date"], y=df["investment_value"], name="Investment value", mode="lines", line=dict(color=BLUE, width=3)))
    fig.add_trace(go.Scatter(x=df["date"], y=df["invested_capital"], name="Invested capital", mode="lines", line=dict(color=INK, width=2, dash="dash")))
    fig.update_layout(title="Investment value vs invested capital", height=380, yaxis_title="Euro", legend=dict(orientation="h", y=1.08))
    return _to_html(fig)


def _empty_chart(title: str) -> str:
    fig = go.Figure()
    fig.add_annotation(text="No data", x=0.5, y=0.5, showarrow=False, font={"size": 16})
    fig.update_layout(title=title, height=320, template="plotly_white", margin=dict(l=40, r=20, t=50, b=40))
    return _to_html(fig)


def _to_html(fig: go.Figure) -> str:
    fig.update_layout(template="plotly_white", autosize=True, margin=dict(l=45, r=25, t=70, b=45), hovermode="x unified")
    return fig.to_html(full_html=False, include_plotlyjs=False, config=PLOT_CONFIG)
