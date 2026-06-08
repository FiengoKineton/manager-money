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
                hovertemplate="%{x}<br>" + label + ": €%{y:.2f}<extra></extra>",
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
            hovertemplate="%{x}<br>Expenses: €%{y:.2f}<extra></extra>",
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
            hovertemplate="%{x}<br>Balance: €%{y:.2f}<extra></extra>",
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
            hovertemplate="%{x}<br>Daily net: €%{y:.2f}<extra></extra>",
        )
    )

    fig.add_trace(
        go.Scatter(
            x=df_roll["date"],
            y=df_roll["rolling_net"],
            mode="lines",
            name="Rolling 30-day net",
            line=dict(color=TYPE_COLORS["income"], width=2.5),
            hovertemplate="%{x}<br>Rolling net: €%{y:.2f}<extra></extra>",
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
            hovertemplate="%{x}<br>Expenses: €%{y:.2f}<extra></extra>",
        )
    )

    fig.update_layout(
        title="Expenses by weekday",
        height=340,
        yaxis_title="Total (€)",
    )

    return _to_html(fig)