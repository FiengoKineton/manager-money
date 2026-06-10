from __future__ import annotations

from dataclasses import dataclass

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


def build_forecast_defaults() -> dict:
    df = load_all()
    main_df = main_account_transactions(df)
    monthly = monthly_summary(main_df)
    recent = _recent_complete_months(monthly, months=6)

    avg_income = _mean(recent, "income")
    avg_spending = _mean(recent, "expenses")

    totals = summary_totals(main_df)
    cash = float(totals.get("net", 0.0) or 0.0) + auxiliary_total(df)
    investment_overview = overview_snapshot(refresh=False)
    investment_habits = investment_habit_snapshot(refresh=False)

    starting_value = float(investment_overview.get("estimated_value", 0.0) or 0.0)
    starting_capital = float(investment_overview.get("net_invested", 0.0) or 0.0)
    if abs(starting_value) < 0.01:
        starting_value = starting_capital

    annual_return = float(investment_habits.get("annual_return_pct", 0.0) or 0.0)
    if abs(annual_return) < 0.01 and abs(investment_habits.get("profit_loss_pct", 0.0) or 0.0) > 0.01:
        annual_return = float(investment_habits.get("profit_loss_pct", 0.0) or 0.0)
    if abs(annual_return) < 0.01:
        annual_return = 5.0

    params = ForecastParams(
        years=5,
        monthly_income=avg_income,
        monthly_spending=avg_spending,
        monthly_net_investment=float(investment_habits.get("monthly_net_investment", 0.0) or 0.0),
        annual_return_pct=annual_return,
        annual_income_growth_pct=0.0,
        annual_spending_growth_pct=2.0,
        starting_cash=cash,
        starting_investment_value=starting_value,
        starting_invested_capital=starting_capital,
        monthly_dividends=float(investment_habits.get("monthly_dividends", 0.0) or 0.0),
    )

    return {
        "params": params,
        "months_used": int(len(recent)),
        "investment_habits": investment_habits,
        "basis": {
            "main_net": float(totals.get("net", 0.0) or 0.0),
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

    cash = float(params.starting_cash)
    investment_value = float(params.starting_investment_value)
    invested_capital = float(params.starting_invested_capital)
    current_income = float(params.monthly_income)
    current_spending = float(params.monthly_spending)
    current_net_investment = float(params.monthly_net_investment)
    dividends = float(params.monthly_dividends)

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
        return float(form.get(key, default))
    except (TypeError, ValueError):
        return float(default or 0.0)


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
    return float(pd.to_numeric(df[column], errors="coerce").fillna(0.0).mean())


def _monthly_rate(annual_pct: float) -> float:
    annual = max(float(annual_pct or 0.0), -99.0) / 100.0
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
