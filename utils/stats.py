# utils/stats.py
import pandas as pd

WEEKDAY_ORDER = ["Monday", "Tuesday", "Wednesday",
                 "Thursday", "Friday", "Saturday", "Sunday"]

def summary_totals(df: pd.DataFrame) -> dict:
    """Return total income, expense, investment, net and savings rate."""
    income = df[df["type"] == "income"]["signed_amount"].sum()
    # signed_amount for expenses & investments is negative
    expenses = df[df["type"] == "expense"]["signed_amount"].sum()
    investments = df[df["type"] == "investment"]["signed_amount"].sum()
    net = df["signed_amount"].sum()

    # convert expenses/investments back to positive for reporting
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
        "total_availability": float(net) + float(investments_abs)
    }



def monthly_summary(df: pd.DataFrame, start: str | None = None, end: str | None = None) -> pd.DataFrame:
    """Income, expenses, investments, net per month over [start, end], with all months included."""
    if df.empty:
        return pd.DataFrame(columns=["month", "income", "expenses", "investments", "net"])

    # Determine month range from selected dates
    if start:
        start_dt = pd.to_datetime(start, errors="coerce")
    else:
        start_dt = df["date"].min()

    if end:
        end_dt = pd.to_datetime(end, errors="coerce")
    else:
        end_dt = df["date"].max()

    if pd.isna(start_dt) or pd.isna(end_dt):
        return pd.DataFrame(columns=["month", "income", "expenses", "investments", "net"])

    # Month range from start month to end month
    month_range = pd.period_range(start=start_dt.to_period("M"),
                                  end=end_dt.to_period("M"),
                                  freq="M")
    month_index = month_range.astype(str)

    df = df.copy()
    df["month"] = df["date"].dt.to_period("M")

    def agg_signed(sub):
        income = sub[sub["type"] == "income"]["signed_amount"].sum()
        expenses = sub[sub["type"] == "expense"]["signed_amount"].sum()
        investments = sub[sub["type"] == "investment"]["signed_amount"].sum()
        net = sub["signed_amount"].sum()
        # positive for reporting
        return pd.Series({
            "income": income,
            "expenses": -expenses,
            "investments": -investments,
            "net": net,
        })

    grouped = df.groupby("month").apply(agg_signed)
    grouped.index = grouped.index.astype(str)

    # Reindex over full month grid, fill missing with 0
    grouped = grouped.reindex(month_index, fill_value=0.0).reset_index()
    grouped = grouped.rename(columns={"index": "month"})
    return grouped



def expenses_by_category(df: pd.DataFrame) -> pd.DataFrame:
    """Total expenses per category."""
    ex = df[df["type"] == "expense"]
    if ex.empty:
        return pd.DataFrame(columns=["category", "total"])
    grouped = ex.groupby("category")["signed_amount"].sum().reset_index()
    grouped["total"] = -grouped["signed_amount"]
    grouped = grouped.drop(columns=["signed_amount"])
    return grouped.sort_values(by="total", ascending=False)


def cumulative_balance(df: pd.DataFrame) -> pd.DataFrame:
    """Cumulative sum of signed_amount ordered by date."""
    if df.empty:
        return pd.DataFrame(columns=["date", "balance"])
    df = df.sort_values(by="date")
    cum = df[["date", "signed_amount"]].copy()
    cum["balance"] = cum["signed_amount"].cumsum()
    return cum[["date", "balance"]]



def weekday_spending(df: pd.DataFrame) -> pd.DataFrame:
    """
    Total expenses per weekday.
    """
    d = df[df["type"] == "expense"].copy()
    if d.empty:
        return pd.DataFrame(columns=["weekday_num", "weekday", "total"])

    d["weekday_num"] = d["date"].dt.weekday
    d["weekday"] = d["date"].dt.day_name()

    out = (
        d.groupby(["weekday_num", "weekday"])["amount"]
        .sum()
        .reset_index()
        .rename(columns={"amount": "total"})
        .sort_values("weekday_num")
    )
    return out


def rolling_net_flow(df: pd.DataFrame, window: int = 30) -> pd.DataFrame:
    """
    Daily net cash flow and rolling window sum.
    """
    if df.empty:
        return pd.DataFrame(columns=["date", "daily_net", "rolling_net"])

    d = df.copy()
    sign = d["type"].map({"income": 1.0, "expense": -1.0, "investment": 0.0}).fillna(0.0)
    d["signed_amount"] = d["amount"] * sign

    daily = (
        d.groupby("date")["signed_amount"]
        .sum()
        .reset_index()
        .rename(columns={"signed_amount": "daily_net"})
        .sort_values("date")
    )
    daily["rolling_net"] = daily["daily_net"].rolling(window, min_periods=1).sum()
    return daily


def largest_expenses(df: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    """
    Top-n expense transactions by amount.
    """
    d = df[df["type"] == "expense"].copy()
    if d.empty:
        return pd.DataFrame(columns=df.columns)

    return d.sort_values("amount", ascending=False).head(n)


def expenses_by_weekday(df):
    """
    Return a DataFrame with total expenses per weekday.

    Columns: weekday, total
    """
    if df.empty:
        return pd.DataFrame(columns=["weekday", "total"])

    tmp = df.copy()
    # assume df["date"] is datetime; if not, this will blow up and you *should* fix it
    tmp["weekday"] = tmp["date"].dt.day_name()

    # only expenses; amount_signed should be negative for expenses
    if "amount_signed" in tmp.columns:
        mask = tmp["type"] == "expense"
        grp = (
            tmp[mask]
            .groupby("weekday", as_index=False)["amount_signed"]
            .sum()
        )
        grp["total"] = -grp["amount_signed"]
    else:
        # fallback: amount is positive, just sum it for expenses
        mask = tmp["type"] == "expense"
        grp = (
            tmp[mask]
            .groupby("weekday", as_index=False)["amount"]
            .sum()
            .rename(columns={"amount": "total"})
        )

    # order Monday → Sunday
    grp = grp.set_index("weekday").reindex(WEEKDAY_ORDER).reset_index()
    grp = grp.dropna(subset=["total"])

    return grp[["weekday", "total"]]


def period_income_expense(df: pd.DataFrame) -> dict:
    """Calculate income and expenses for a given time period."""
    if df.empty:
        return {"income": 0.0, "expenses": 0.0}
        
    income = df[df["type"] == "income"]["signed_amount"].sum()
    
    # We use a minus sign here because expenses are stored as negative numbers 
    # in 'signed_amount', and we want to display them as positive totals.
    expenses = -df[df["type"] == "expense"]["signed_amount"].sum()
    
    return {"income": float(income), "expenses": float(expenses)}
