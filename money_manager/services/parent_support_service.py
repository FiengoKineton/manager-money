from datetime import date

import pandas as pd

from money_manager.config.categories import (
    DEFAULT_PARENT_SUPPORT_CATEGORY,
    PARENT_SUPPORT_CATEGORIES,
    PARENT_SUPPORT_KINDS,
)
from money_manager.repositories.parent_support import append_entry, delete_entry, load_entries

KIND_DIRECT_MONEY = "direct_money"
KIND_COVERED_EXPENSE = "covered_expense"


def parse_amount(value) -> float:
    text = str(value or "0").replace(",", ".")
    try:
        return max(0.0, float(text))
    except ValueError:
        return 0.0


def add_entry_from_form(form) -> None:
    kind = form.get("kind", KIND_DIRECT_MONEY)
    if kind not in PARENT_SUPPORT_KINDS:
        kind = KIND_DIRECT_MONEY

    category = form.get("category", DEFAULT_PARENT_SUPPORT_CATEGORY).strip()
    if not category:
        category = DEFAULT_PARENT_SUPPORT_CATEGORY

    append_entry({
        "date": form.get("date", date.today().isoformat()),
        "kind": kind,
        "parent": form.get("parent", ""),
        "category": category,
        "amount": parse_amount(form.get("amount")),
        "payment_method": form.get("payment_method", ""),
        "description": form.get("description", ""),
    })


def delete_entry_from_form(form) -> None:
    try:
        delete_entry(int(form.get("id")))
    except (TypeError, ValueError):
        return


def page_context(start: str, end: str) -> dict:
    df = entries_frame()
    filtered = filter_by_date(df, start, end)
    totals = totals_from_frame(filtered)

    return {
        "entries": prepare_for_display(filtered),
        "totals": totals,
        "monthly": monthly_summary(filtered),
        "category_summary": category_summary(filtered),
        "kind_labels": PARENT_SUPPORT_KINDS,
        "categories": PARENT_SUPPORT_CATEGORIES,
        "default_category": DEFAULT_PARENT_SUPPORT_CATEGORY,
    }


def overview_totals(start: str | None = None, end: str | None = None) -> dict:
    df = entries_frame()
    if start or end:
        df = filter_by_date(df, start, end)
    return totals_from_frame(df)


def entries_frame() -> pd.DataFrame:
    rows = load_entries()
    if not rows:
        return pd.DataFrame(columns=[
            "id", "date", "kind", "parent", "category", "amount", "payment_method", "description", "created_at"
        ])

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["created_at"] = pd.to_datetime(df.get("created_at"), errors="coerce")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    return df.sort_values(by=["date", "created_at"], ascending=[False, False])


def filter_by_date(df: pd.DataFrame, start: str | None, end: str | None) -> pd.DataFrame:
    if df.empty:
        return df

    filtered = df.copy()
    start_dt = pd.to_datetime(start, errors="coerce") if start else None
    end_dt = pd.to_datetime(end, errors="coerce") if end else None

    if start_dt is not None and not pd.isna(start_dt):
        filtered = filtered[filtered["date"] >= start_dt]
    if end_dt is not None and not pd.isna(end_dt):
        filtered = filtered[filtered["date"] <= end_dt]

    return filtered


def totals_from_frame(df: pd.DataFrame) -> dict:
    direct_money = sum_kind(df, KIND_DIRECT_MONEY)
    covered_expenses = sum_kind(df, KIND_COVERED_EXPENSE)
    total_support = direct_money + covered_expenses

    return {
        "direct_money": direct_money,
        "covered_expenses": covered_expenses,
        "total_support": total_support,
    }


def sum_kind(df: pd.DataFrame, kind: str) -> float:
    if df.empty:
        return 0.0
    return float(df.loc[df["kind"] == kind, "amount"].sum())


def monthly_summary(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []

    summary = df.dropna(subset=["date"]).copy()
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
            "direct_money": float(row.get(KIND_DIRECT_MONEY, 0.0)),
            "covered_expenses": float(row.get(KIND_COVERED_EXPENSE, 0.0)),
            "total_support": float(row.get(KIND_DIRECT_MONEY, 0.0)) + float(row.get(KIND_COVERED_EXPENSE, 0.0)),
        })
    return rows


def category_summary(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []

    work = df.copy()
    work["category"] = work["category"].fillna("Uncategorized").replace("", "Uncategorized")
    grouped = (
        work.groupby("category", dropna=False)["amount"]
        .sum()
        .reset_index()
        .rename(columns={"amount": "total"})
        .sort_values("total", ascending=False)
    )
    return grouped.to_dict(orient="records")


def prepare_for_display(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []

    display = df.copy()
    display["date_str"] = display["date"].dt.strftime("%Y-%m-%d")
    display["amount_str"] = display["amount"].map(lambda value: f"{value:.2f}")
    display["kind_label"] = display["kind"].map(PARENT_SUPPORT_KINDS).fillna(display["kind"])
    display["category"] = display["category"].fillna("")
    display["parent"] = display["parent"].fillna("")
    display["payment_method"] = display["payment_method"].fillna("")
    display["description"] = display["description"].fillna("")
    return display.to_dict(orient="records")
