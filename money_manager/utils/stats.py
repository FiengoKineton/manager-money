import pandas as pd

from money_manager.domain.constants import WEEKDAY_ORDER


def summary_totals(df: pd.DataFrame) -> dict:
    """Return total income, expense, investment, net and savings rate."""
    income = df[df["type"] == "income"]["signed_amount"].sum()
    expenses = df[df["type"] == "expense"]["signed_amount"].sum()
    investments = df[df["type"] == "investment"]["signed_amount"].sum()
    net = df["signed_amount"].sum()

    expenses_abs = -expenses
    investments_abs = -investments

    savings_rate = 0.0
    if income > 1e-9:
        savings_rate = max(net, 0.0) / income * 100.0

    return {
        "income": float(income),
        "expenses": float(expenses_abs),
        "investments": float(investments_abs),
        "net": float(net),
        "savings_rate": float(savings_rate),
        "total_availability": float(net) + float(investments_abs),
    }


def monthly_summary(df: pd.DataFrame, start: str | None = None, end: str | None = None) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["month", "income", "expenses", "investments", "net"])

    start_dt = pd.to_datetime(start, errors="coerce") if start else df["date"].min()
    end_dt = pd.to_datetime(end, errors="coerce") if end else df["date"].max()

    if pd.isna(start_dt) or pd.isna(end_dt):
        return pd.DataFrame(columns=["month", "income", "expenses", "investments", "net"])

    month_range = pd.period_range(start=start_dt.to_period("M"), end=end_dt.to_period("M"), freq="M")
    month_index = month_range.astype(str)

    df = df.copy()
    df["month"] = df["date"].dt.to_period("M")

    def aggregate(sub):
        income = sub[sub["type"] == "income"]["signed_amount"].sum()
        expenses = sub[sub["type"] == "expense"]["signed_amount"].sum()
        investments = sub[sub["type"] == "investment"]["signed_amount"].sum()
        net = sub["signed_amount"].sum()
        return pd.Series({
            "income": income,
            "expenses": -expenses,
            "investments": -investments,
            "net": net,
        })

    grouped = df.groupby("month").apply(aggregate)
    grouped.index = grouped.index.astype(str)
    grouped = grouped.reindex(month_index, fill_value=0.0).reset_index()
    return grouped.rename(columns={"index": "month"})


def expenses_by_category(df: pd.DataFrame) -> pd.DataFrame:
    expenses = df[df["type"] == "expense"]
    if expenses.empty:
        return pd.DataFrame(columns=["category", "total"])

    grouped = expenses.groupby("category")["signed_amount"].sum().reset_index()
    grouped["total"] = -grouped["signed_amount"]
    return grouped.drop(columns=["signed_amount"]).sort_values(by="total", ascending=False)


def cumulative_balance(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["date", "balance"])

    df = df.sort_values(by="date")
    cum = df[["date", "signed_amount"]].copy()
    cum["balance"] = cum["signed_amount"].cumsum()
    return cum[["date", "balance"]]


def weekday_spending(df: pd.DataFrame) -> pd.DataFrame:
    expenses = df[df["type"] == "expense"].copy()
    if expenses.empty:
        return pd.DataFrame(columns=["weekday_num", "weekday", "total"])

    expenses["weekday_num"] = expenses["date"].dt.weekday
    expenses["weekday"] = expenses["date"].dt.day_name()

    return (
        expenses.groupby(["weekday_num", "weekday"])["amount"]
        .sum()
        .reset_index()
        .rename(columns={"amount": "total"})
        .sort_values("weekday_num")
    )


def rolling_net_flow(df: pd.DataFrame, window: int = 30) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["date", "daily_net", "rolling_net"])

    daily = (
        df.groupby("date")["signed_amount"]
        .sum()
        .reset_index()
        .rename(columns={"signed_amount": "daily_net"})
        .sort_values("date")
    )
    daily["rolling_net"] = daily["daily_net"].rolling(window, min_periods=1).sum()
    return daily


def largest_expenses(df: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    expenses = df[df["type"] == "expense"].copy()
    if expenses.empty:
        return pd.DataFrame(columns=df.columns)
    return expenses.sort_values("amount", ascending=False).head(n)


def expenses_by_weekday(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["weekday", "total"])

    tmp = df.copy()
    tmp["weekday"] = tmp["date"].dt.day_name()
    expenses = tmp[tmp["type"] == "expense"]
    grouped = expenses.groupby("weekday", as_index=False)["amount"].sum().rename(columns={"amount": "total"})
    grouped = grouped.set_index("weekday").reindex(WEEKDAY_ORDER).reset_index()
    grouped = grouped.dropna(subset=["total"])
    return grouped[["weekday", "total"]]


def period_income_expense(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"income": 0.0, "expenses": 0.0}

    income = df[df["type"] == "income"]["signed_amount"].sum()
    expenses = -df[df["type"] == "expense"]["signed_amount"].sum()
    return {"income": float(income), "expenses": float(expenses)}
