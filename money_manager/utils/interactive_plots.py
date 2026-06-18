import plotly.graph_objects as go


PLOT_CONFIG = {
    "displaylogo": False,
    "responsive": True,
    "modeBarButtonsToRemove": ["lasso2d", "select2d"],
}

TYPE_COLORS = {
    "income": "#1b5e20",
    "expenses": "#b00020",
    "expense": "#b00020",
    "investments": "#222222",
    "investment": "#222222",
    "net": "#0057b8",
    "balance": "#0057b8",
}

def _empty_chart(title):
    fig = go.Figure()
    fig.add_annotation(
        text="No data",
        x=0.5,
        y=0.5,
        showarrow=False,
        font={"size": 16},
    )
    fig.update_layout(
        title=title,
        height=320,
        template="plotly_white",
        margin=dict(l=40, r=20, t=50, b=40),
    )
    return _to_html(fig)


def _to_html(fig):
    fig.update_layout(
        template="plotly_white",
        autosize=True,
        margin=dict(l=45, r=20, t=50, b=45),
        hovermode="x unified",
    )

    return fig.to_html(
        full_html=False,
        include_plotlyjs=False,
        config=PLOT_CONFIG,
    )


def chart_monthly_summary(df_monthly):
    if df_monthly is None or df_monthly.empty:
        return _empty_chart("Monthly summary")

    fig = go.Figure()

    for col, label, color_key in [
        ("income", "Income", "income"),
        ("expenses", "Expenses", "expenses"),
        ("investments", "Investments", "investments"),
        ("net", "Net", "net"),
    ]:
        fig.add_trace(
            go.Scatter(
                x=df_monthly["month"],
                y=df_monthly[col],
                mode="lines+markers",
                name=label,
                line=dict(color=TYPE_COLORS[color_key], width=2.5),
                marker=dict(color=TYPE_COLORS[color_key], size=7),
                hovertemplate="%{x}<br>" + label + ": €%{y:,.2f}<extra></extra>",
            )
        )

    fig.update_layout(
        title="Monthly summary",
        height=340,
        yaxis_title="Amount (€)",
    )

    return _to_html(fig)


def chart_expenses_by_category(df_cat):
    if df_cat is None or df_cat.empty:
        return _empty_chart("Expenses by category")

    fig = go.Figure()

    fig.add_trace(
        go.Bar(
            x=df_cat["category"],
            y=df_cat["total"],
            marker_color=TYPE_COLORS["expenses"],
            hovertemplate="%{x}<br>Expenses: €%{y:,.2f}<extra></extra>",
        )
    )

    fig.update_layout(
        title="Expenses by category",
        height=340,
        yaxis_title="Total (€)",
        xaxis_tickangle=-45,
    )

    return _to_html(fig)


def chart_cumulative_balance(df_cum):
    if df_cum is None or df_cum.empty:
        return _empty_chart("Cumulative balance")

    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=df_cum["date"],
            y=df_cum["balance"],
            mode="lines+markers",
            name="Balance",
            line=dict(color=TYPE_COLORS["balance"], width=2.5),
            marker=dict(color=TYPE_COLORS["balance"], size=6),
            hovertemplate="%{x}<br>Balance: €%{y:,.2f}<extra></extra>",
        )
    )

    fig.update_layout(
        title="Cumulative balance",
        height=340,
        yaxis_title="Balance (€)",
    )

    return _to_html(fig)


def chart_rolling_net_flow(df_roll):
    if df_roll is None or df_roll.empty:
        return _empty_chart("Net cash flow")

    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=df_roll["date"],
            y=df_roll["daily_net"],
            mode="lines",
            name="Daily net",
            line=dict(color=TYPE_COLORS["net"], width=1.8),
            hovertemplate="%{x}<br>Daily net: €%{y:,.2f}<extra></extra>",
        )
    )

    fig.add_trace(
        go.Scatter(
            x=df_roll["date"],
            y=df_roll["rolling_net"],
            mode="lines",
            name="Rolling 30-day net",
            line=dict(color=TYPE_COLORS["income"], width=2.5),
            hovertemplate="%{x}<br>Rolling net: €%{y:,.2f}<extra></extra>",
        )
    )

    fig.update_layout(
        title="Net cash flow",
        height=340,
        yaxis_title="Amount (€)",
    )

    return _to_html(fig)


def chart_weekday_spending(df_wd):
    if df_wd is None or df_wd.empty:
        return _empty_chart("Expenses by weekday")

    fig = go.Figure()

    fig.add_trace(
        go.Bar(
            x=df_wd["weekday"],
            y=df_wd["total"],
            marker_color=TYPE_COLORS["expenses"],
            hovertemplate="%{x}<br>Expenses: €%{y:,.2f}<extra></extra>",
        )
    )

    fig.update_layout(
        title="Expenses by weekday",
        height=340,
        yaxis_title="Total (€)",
    )

    return _to_html(fig)

def chart_cashflow_waterfall(statement):
    statement = statement or {}
    income = float(statement.get("income", 0.0) or 0.0)
    expenses = float(statement.get("expenses", 0.0) or 0.0)
    investments = float(statement.get("investments", 0.0) or 0.0)
    net = float(statement.get("net", 0.0) or 0.0)

    if abs(income) <= 1e-9 and abs(expenses) <= 1e-9 and abs(investments) <= 1e-9:
        return _empty_chart("Cashflow bridge")

    fig = go.Figure(
        go.Waterfall(
            name="Cashflow",
            orientation="v",
            measure=["relative", "relative", "relative", "total"],
            x=["Income", "Expenses", "Investments", "Net"],
            y=[income, -expenses, -investments, net],
            text=[f"€{income:,.2f}", f"-€{expenses:,.2f}", f"-€{investments:,.2f}", f"€{net:,.2f}"],
            textposition="outside",
            connector={"line": {"color": "rgba(148, 163, 184, 0.55)"}},
            hovertemplate="%{x}<br>€%{y:,.2f}<extra></extra>",
        )
    )
    fig.update_layout(
        title="Cashflow bridge",
        height=360,
        yaxis_title="Amount (€)",
    )
    return _to_html(fig)


def chart_income_sources(income_sources):
    if not income_sources:
        return _empty_chart("Income sources")

    labels = [row.get("source", "Income") for row in income_sources]
    values = [float(row.get("total", 0.0) or 0.0) for row in income_sources]
    if sum(values) <= 1e-9:
        return _empty_chart("Income sources")

    fig = go.Figure(
        go.Bar(
            x=values,
            y=labels,
            orientation="h",
            marker_color=TYPE_COLORS["income"],
            hovertemplate="%{y}<br>Income: €%{x:,.2f}<extra></extra>",
        )
    )
    fig.update_layout(
        title="Income sources",
        height=340,
        xaxis_title="Income (€)",
        yaxis={"categoryorder": "total ascending"},
    )
    return _to_html(fig)


def chart_spending_pareto(df_cat):
    if df_cat is None or df_cat.empty:
        return _empty_chart("Spending concentration")

    df = df_cat.copy().sort_values("total", ascending=False).head(10)
    total = float(df["total"].sum() or 0.0)
    if total <= 1e-9:
        return _empty_chart("Spending concentration")
    df["cum_share"] = df["total"].cumsum() / total * 100.0

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=df["category"],
            y=df["total"],
            name="Expenses",
            marker_color=TYPE_COLORS["expenses"],
            hovertemplate="%{x}<br>Expenses: €%{y:,.2f}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=df["category"],
            y=df["cum_share"],
            name="Cumulative share",
            yaxis="y2",
            mode="lines+markers",
            line=dict(color=TYPE_COLORS["net"], width=2.5),
            marker=dict(color=TYPE_COLORS["net"], size=7),
            hovertemplate="%{x}<br>Cumulative: %{y:.1f}%<extra></extra>",
        )
    )
    fig.update_layout(
        title="Spending concentration",
        height=360,
        yaxis_title="Expenses (€)",
        yaxis2=dict(title="Cumulative %", overlaying="y", side="right", range=[0, 105]),
        xaxis_tickangle=-35,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )
    return _to_html(fig)


def chart_monthly_savings_rate(df_monthly):
    if df_monthly is None or df_monthly.empty:
        return _empty_chart("Monthly retention rate")

    df = df_monthly.copy()
    for col in ["income", "expenses", "investments", "net"]:
        if col not in df.columns:
            df[col] = 0.0
    df["expense_ratio"] = df.apply(lambda row: 0.0 if float(row["income"] or 0.0) <= 0 else float(row["expenses"] or 0.0) / float(row["income"] or 1.0) * 100.0, axis=1)
    df["investment_ratio"] = df.apply(lambda row: 0.0 if float(row["income"] or 0.0) <= 0 else float(row["investments"] or 0.0) / float(row["income"] or 1.0) * 100.0, axis=1)
    df["leftover_ratio"] = df.apply(lambda row: 0.0 if float(row["income"] or 0.0) <= 0 else float(row["net"] or 0.0) / float(row["income"] or 1.0) * 100.0, axis=1)

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=df["month"],
            y=df["expense_ratio"],
            mode="lines+markers",
            name="Spent",
            line=dict(color=TYPE_COLORS["expenses"], width=2.4),
            marker=dict(color=TYPE_COLORS["expenses"], size=7),
            hovertemplate="%{x}<br>Spent: %{y:.1f}%<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=df["month"],
            y=df["investment_ratio"],
            mode="lines+markers",
            name="Invested",
            line=dict(color=TYPE_COLORS["investments"], width=2.4),
            marker=dict(color=TYPE_COLORS["investments"], size=7),
            hovertemplate="%{x}<br>Invested: %{y:.1f}%<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=df["month"],
            y=df["leftover_ratio"],
            mode="lines+markers",
            name="Leftover net",
            line=dict(color=TYPE_COLORS["net"], width=2.4),
            marker=dict(color=TYPE_COLORS["net"], size=7),
            hovertemplate="%{x}<br>Leftover net: %{y:.1f}%<extra></extra>",
        )
    )
    fig.update_layout(
        title="Monthly income allocation",
        height=340,
        yaxis_title="Share of income (%)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )
    return _to_html(fig)
