from calendar import monthrange
from datetime import date, datetime

import pandas as pd

from money_manager.config.categories import (
    DEFAULT_PARENT_SUPPORT_CATEGORY,
    PARENT_SUPPORT_CATEGORIES,
    PARENT_SUPPORT_KINDS,
)
from money_manager.repositories.parent_support import (
    append_entry,
    append_rule,
    delete_entry,
    delete_rule,
    load_entries,
    load_rules,
    update_entry,
    update_rule,
)

KIND_DIRECT_MONEY = "direct_money"
KIND_COVERED_EXPENSE = "covered_expense"


def parse_amount(value) -> float:
    text = str(value or "0").replace(",", ".")
    try:
        return max(0.0, float(text))
    except ValueError:
        return 0.0

def parse_int(value, default: int = 1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_date(value):
    if not value:
        return None

    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None

    return parsed.date()


def is_active(value) -> bool:
    return str(value).strip().lower() in {"yes", "true", "1", "active", "on"}


def add_rule_from_form(form) -> None:
    kind = form.get("kind", KIND_COVERED_EXPENSE)
    if kind not in PARENT_SUPPORT_KINDS:
        kind = KIND_COVERED_EXPENSE

    category = form.get("category", DEFAULT_PARENT_SUPPORT_CATEGORY).strip()
    if not category:
        category = DEFAULT_PARENT_SUPPORT_CATEGORY

    append_rule({
        "name": form.get("name", "").strip(),
        "kind": kind,
        "parent": form.get("parent", "").strip(),
        "category": category,
        "monthly_amount": parse_amount(form.get("monthly_amount")),
        "day_of_month": max(1, min(31, parse_int(form.get("day_of_month"), 1))),
        "start_date": form.get("start_date", date.today().isoformat()),
        "end_date": form.get("end_date", ""),
        "payment_method": form.get("payment_method", ""),
        "description": form.get("description", ""),
        "active": "yes",
    })


def delete_rule_from_form(form) -> None:
    try:
        delete_rule(int(form.get("id")))
    except (TypeError, ValueError):
        return


def update_rule_from_form(form) -> None:
    try:
        rule_id = int(form.get("id"))
    except (TypeError, ValueError):
        return

    kind = form.get("kind", KIND_COVERED_EXPENSE)
    if kind not in PARENT_SUPPORT_KINDS:
        kind = KIND_COVERED_EXPENSE

    update_rule(rule_id, {
        "name": form.get("name", "").strip(),
        "kind": kind,
        "parent": form.get("parent", "").strip(),
        "category": form.get("category", DEFAULT_PARENT_SUPPORT_CATEGORY).strip() or DEFAULT_PARENT_SUPPORT_CATEGORY,
        "monthly_amount": parse_amount(form.get("monthly_amount")),
        "day_of_month": max(1, min(31, parse_int(form.get("day_of_month"), 1))),
        "start_date": form.get("start_date", ""),
        "end_date": form.get("end_date", ""),
        "payment_method": form.get("payment_method", ""),
        "description": form.get("description", ""),
        "active": "yes" if form.get("active") else "no",
    })


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


def update_entry_from_form(form) -> None:
    try:
        entry_id = int(form.get("id"))
    except (TypeError, ValueError):
        return

    kind = form.get("kind", KIND_DIRECT_MONEY)
    if kind not in PARENT_SUPPORT_KINDS:
        kind = KIND_DIRECT_MONEY

    update_entry(entry_id, {
        "date": form.get("date", date.today().isoformat()),
        "kind": kind,
        "parent": form.get("parent", ""),
        "category": form.get("category", DEFAULT_PARENT_SUPPORT_CATEGORY).strip() or DEFAULT_PARENT_SUPPORT_CATEGORY,
        "amount": parse_amount(form.get("amount")),
        "payment_method": form.get("payment_method", ""),
        "description": form.get("description", ""),
    })


def page_context(start: str, end: str) -> dict:
    df = entries_frame(start, end)
    filtered = filter_by_date(df, start, end)
    totals = totals_from_frame(filtered)

    return {
        "entries": prepare_for_display(filtered),
        "rules": prepare_rules_for_display(),
        "totals": totals,
        "monthly": monthly_summary(filtered),
        "category_summary": category_summary(filtered),
        "kind_labels": PARENT_SUPPORT_KINDS,
        "categories": PARENT_SUPPORT_CATEGORIES,
        "default_category": DEFAULT_PARENT_SUPPORT_CATEGORY,
    }


def overview_totals(start: str | None = None, end: str | None = None) -> dict:
    df = entries_frame(start, end)
    if start or end:
        df = filter_by_date(df, start, end)
    return totals_from_frame(df)


def entries_frame(start: str | None = None, end: str | None = None) -> pd.DataFrame:
    manual_rows = load_entries()
    generated_rows = generate_monthly_rule_entries(start, end)

    rows = [*manual_rows, *generated_rows]

    if not rows:
        return pd.DataFrame(columns=[
            "id",
            "date",
            "kind",
            "parent",
            "category",
            "amount",
            "payment_method",
            "description",
            "created_at",
            "generated",
            "rule_id",
        ])

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["created_at"] = pd.to_datetime(df.get("created_at"), errors="coerce")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)

    if "generated" not in df.columns:
        df["generated"] = "no"

    if "rule_id" not in df.columns:
        df["rule_id"] = ""

    return df.sort_values(by=["date", "created_at"], ascending=[False, False])

def generate_monthly_rule_entries(start: str | None, end: str | None) -> list[dict]:
    rules = load_rules()

    start_date = parse_date(start) or date(date.today().year, 1, 1)
    end_date = parse_date(end) or date.today()

    generated = []

    for rule in rules:
        if not is_active(rule.get("active", "yes")):
            continue

        amount = parse_amount(rule.get("monthly_amount"))
        if amount <= 0:
            continue

        rule_start = parse_date(rule.get("start_date")) or start_date
        rule_end = parse_date(rule.get("end_date")) or end_date

        effective_start = max(start_date, rule_start)
        effective_end = min(end_date, rule_end)

        if effective_start > effective_end:
            continue

        day_of_month = max(1, min(31, parse_int(rule.get("day_of_month"), 1)))

        current = date(effective_start.year, effective_start.month, 1)
        last_month = date(effective_end.year, effective_end.month, 1)

        while current <= last_month:
            last_day = monthrange(current.year, current.month)[1]
            occurrence_day = min(day_of_month, last_day)
            occurrence_date = date(current.year, current.month, occurrence_day)

            if effective_start <= occurrence_date <= effective_end:
                rule_id = rule.get("id", "")
                month_key = occurrence_date.strftime("%Y-%m")

                generated.append({
                    "id": f"rule-{rule_id}-{month_key}",
                    "date": occurrence_date.isoformat(),
                    "kind": rule.get("kind", KIND_COVERED_EXPENSE),
                    "parent": rule.get("parent", ""),
                    "category": rule.get("category", ""),
                    "amount": amount,
                    "payment_method": rule.get("payment_method", ""),
                    "description": rule.get("description", rule.get("name", "")),
                    "created_at": rule.get("created_at", ""),
                    "generated": "yes",
                    "rule_id": rule_id,
                })

            current = next_month(current)

    return generated


def next_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def prepare_rules_for_display() -> list[dict]:
    rules = load_rules()
    prepared = []

    for rule in rules:
        prepared.append({
            "id": rule.get("id", ""),
            "name": rule.get("name", ""),
            "kind": rule.get("kind", ""),
            "kind_label": PARENT_SUPPORT_KINDS.get(rule.get("kind", ""), rule.get("kind", "")),
            "parent": rule.get("parent", ""),
            "category": rule.get("category", ""),
            "monthly_amount": parse_amount(rule.get("monthly_amount")),
            "monthly_amount_str": f"{parse_amount(rule.get('monthly_amount')):.2f}",
            "day_of_month": rule.get("day_of_month", "1"),
            "start_date": rule.get("start_date", ""),
            "end_date": rule.get("end_date", ""),
            "payment_method": rule.get("payment_method", ""),
            "description": rule.get("description", ""),
            "active": is_active(rule.get("active", "yes")),
        })

    return prepared

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

    if "generated" not in display.columns:
        display["generated"] = "no"

    display["generated_label"] = display["generated"].map({
        "yes": "Monthly rule",
        "no": "Manual",
    }).fillna("Manual")

    return display.to_dict(orient="records")
