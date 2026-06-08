from datetime import date

import pandas as pd

from money_manager.repositories.sparagnat import append_entry, delete_entry, load_entries
from money_manager.services.analytics_service import apply_transaction_filters, build_dashboard_metrics
from money_manager.services.account_service import main_account_transactions
from money_manager.services.transaction_service import load_transactions

KIND_SAVED_EXPENSE = "saved_expense"
KIND_CASH_COLLECTED = "cash_collected"
KIND_LABELS = {
    KIND_SAVED_EXPENSE: "Expense paid by someone else",
    KIND_CASH_COLLECTED: "Cash collected",
}


def parse_amount(value) -> float:
    text = str(value or "0").replace(",", ".")
    try:
        return max(0.0, float(text))
    except ValueError:
        return 0.0


def add_entry_from_form(form) -> None:
    kind = form.get("kind", KIND_SAVED_EXPENSE)
    if kind not in KIND_LABELS:
        kind = KIND_SAVED_EXPENSE

    append_entry({
        "date": form.get("date", date.today().isoformat()),
        "kind": kind,
        "person": form.get("person", ""),
        "category": form.get("category", ""),
        "amount": parse_amount(form.get("amount")),
        "account": form.get("account", "cash"),
        "description": form.get("description", ""),
    })


def delete_entry_from_form(form) -> None:
    try:
        delete_entry(int(form.get("id")))
    except (TypeError, ValueError):
        return


def page_context(start: str, end: str) -> dict:
    df = _entries_frame()
    filtered = _filter_by_date(df, start, end)

    saved_total = _sum_kind(filtered, KIND_SAVED_EXPENSE)
    cash_total = _sum_kind(filtered, KIND_CASH_COLLECTED)

    transactions = load_transactions()
    filtered_transactions = apply_transaction_filters(
        transactions, start, end, ["expense", "income", "investment"], [], ""
    )
    filtered_transactions = main_account_transactions(filtered_transactions)
    dashboard_metrics = build_dashboard_metrics(filtered_transactions, start, end)
    current_net = dashboard_metrics["totals"]["net"]

    monthly = _monthly_summary(filtered)

    return {
        "entries": _prepare_for_display(filtered),
        "totals": {
            "saved_expenses": saved_total,
            "cash_collected": cash_total,
            "current_net": current_net,
            "net_if_you_paid": current_net - saved_total,
        },
        "monthly": monthly,
        "kind_labels": KIND_LABELS,
    }



def overview_totals(start: str | None = None, end: str | None = None) -> dict:
    df = _entries_frame()
    if start or end:
        df = _filter_by_date(df, start, end)

    return {
        "saved_expenses": _sum_kind(df, KIND_SAVED_EXPENSE),
        "cash_collected": _sum_kind(df, KIND_CASH_COLLECTED),
    }


def _entries_frame() -> pd.DataFrame:
    rows = load_entries()
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["id", "date", "kind", "person", "category", "amount", "account", "description", "created_at"])

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["created_at"] = pd.to_datetime(df.get("created_at"), errors="coerce")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    return df.sort_values(by=["date", "created_at"], ascending=[False, False])


def _filter_by_date(df: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    if df.empty:
        return df

    filtered = df.copy()
    start_dt = pd.to_datetime(start, errors="coerce")
    end_dt = pd.to_datetime(end, errors="coerce")

    if not pd.isna(start_dt):
        filtered = filtered[filtered["date"] >= start_dt]
    if not pd.isna(end_dt):
        filtered = filtered[filtered["date"] <= end_dt]

    return filtered


def _sum_kind(df: pd.DataFrame, kind: str) -> float:
    if df.empty:
        return 0.0
    return float(df.loc[df["kind"] == kind, "amount"].sum())


def _monthly_summary(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []

    summary = df.copy()
    summary = summary.dropna(subset=["date"])
    if summary.empty:
        return []

    summary["month"] = summary["date"].dt.to_period("M").astype(str)
    pivot = (
        summary.pivot_table(index="month", columns="kind", values="amount", aggfunc="sum", fill_value=0.0)
        .reset_index()
        .sort_values("month", ascending=False)
    )

    rows = []
    for row in pivot.to_dict(orient="records"):
        rows.append({
            "month": row.get("month", ""),
            "saved_expenses": float(row.get(KIND_SAVED_EXPENSE, 0.0)),
            "cash_collected": float(row.get(KIND_CASH_COLLECTED, 0.0)),
        })
    return rows


def _prepare_for_display(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []

    display = df.copy()
    display["date_str"] = display["date"].dt.strftime("%Y-%m-%d")
    display["amount_str"] = display["amount"].map(lambda value: f"{value:.2f}")
    display["kind_label"] = display["kind"].map(KIND_LABELS).fillna(display["kind"])
    return display.to_dict(orient="records")
