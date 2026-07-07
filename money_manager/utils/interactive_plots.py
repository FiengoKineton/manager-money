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



def _positive_items(labels, values):
    items = []
    for label, value in zip(labels, values):
        try:
            amount = float(value or 0.0)
        except (TypeError, ValueError):
            amount = 0.0
        if amount > 1e-9:
            items.append((str(label), amount))
    return items


def _compact_euro(value):
    try:
        value = float(value or 0.0)
    except (TypeError, ValueError):
        value = 0.0
    sign = "-" if value < 0 else ""
    value = abs(value)
    if value >= 1_000_000:
        return f"{sign}€{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{sign}€{value / 1_000:.1f}k"
    return f"{sign}€{value:.0f}"


def chart_dashboard_money_mix(totals):
    totals = totals or {}
    items = _positive_items(
        ["Income", "Expenses", "Investments"],
        [totals.get("income"), totals.get("expenses"), totals.get("investments")],
    )
    if not items:
        return _empty_chart("Money mix")

    labels = [label for label, _ in items]
    values = [value for _, value in items]
    total = sum(values)

    fig = go.Figure(
        go.Pie(
            labels=labels,
            values=values,
            hole=0.58,
            sort=False,
            textinfo="label+percent",
            hovertemplate="%{label}<br>€%{value:,.2f}<br>%{percent}<extra></extra>",
        )
    )
    fig.update_traces(marker={"line": {"color": "rgba(255,255,255,0.9)", "width": 2}})
    fig.update_layout(
        title="Money mix",
        height=410,
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=-0.16, xanchor="center", x=0.5),
        annotations=[dict(text=f"Total<br>{_compact_euro(total)}", x=0.5, y=0.5, showarrow=False, font={"size": 16})],
    )
    return _to_html(fig)


def chart_dashboard_expense_donut(df_cat, max_slices=7):
    if df_cat is None or df_cat.empty:
        return _empty_chart("Expense split")

    df = df_cat.copy().sort_values("total", ascending=False)
    df["total"] = df["total"].astype(float)
    head = df.head(max_slices)
    other_total = float(df.iloc[max_slices:]["total"].sum()) if len(df) > max_slices else 0.0
    labels = head["category"].astype(str).tolist()
    values = head["total"].astype(float).tolist()
    if other_total > 1e-9:
        labels.append("Other")
        values.append(other_total)

    items = _positive_items(labels, values)
    if not items:
        return _empty_chart("Expense split")

    labels = [label for label, _ in items]
    values = [value for _, value in items]
    total = sum(values)

    fig = go.Figure(
        go.Pie(
            labels=labels,
            values=values,
            hole=0.54,
            sort=False,
            textinfo="percent",
            hovertemplate="%{label}<br>Expenses: €%{value:,.2f}<br>%{percent}<extra></extra>",
        )
    )
    fig.update_traces(marker={"line": {"color": "rgba(255,255,255,0.9)", "width": 2}})
    fig.update_layout(
        title="Expense split",
        height=410,
        legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="center", x=0.5),
        annotations=[dict(text=f"Spent<br>{_compact_euro(total)}", x=0.5, y=0.5, showarrow=False, font={"size": 16})],
    )
    return _to_html(fig)


def chart_dashboard_balance_area(df_cum):
    if df_cum is None or df_cum.empty:
        return _empty_chart("Balance path")

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=df_cum["date"],
            y=df_cum["balance"],
            mode="lines",
            name="Balance",
            fill="tozeroy",
            line=dict(color=TYPE_COLORS["balance"], width=3),
            hovertemplate="%{x}<br>Balance: €%{y:,.2f}<extra></extra>",
        )
    )

    latest = float(df_cum["balance"].iloc[-1]) if not df_cum.empty else 0.0
    fig.update_layout(
        title="Balance path",
        height=410,
        yaxis_title="Balance (€)",
        showlegend=False,
        annotations=[dict(text=f"Now {_compact_euro(latest)}", xref="paper", yref="paper", x=0.02, y=0.98, showarrow=False, align="left", font={"size": 14})],
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
        height=410,
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
