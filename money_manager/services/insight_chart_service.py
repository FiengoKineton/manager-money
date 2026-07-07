from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pandas as pd

from money_manager.repositories.debts import load_debts
from money_manager.repositories.payables import load_payables
from money_manager.repositories.pending import load_pending
from money_manager.repositories.receivables import load_receivables
from money_manager.repositories.recurring import load_recurring
from money_manager.services.planned_expense_service import active_planned_expenses_for_forecast


def useful_chart_context(transactions: pd.DataFrame | None = None, monthly_summary: pd.DataFrame | None = None) -> dict[str, Any]:
    transactions = transactions if transactions is not None else pd.DataFrame()
    monthly_summary = monthly_summary if monthly_summary is not None else pd.DataFrame()
    return {
        "monthly_income_expenses": _monthly_income_expenses(monthly_summary),
        "category_spending": _category_spending(transactions),
        "account_balance_trend": _account_balance_trend(transactions),
        "debts_progress": _debts_progress(),
        "upcoming_cashflow": _upcoming_cashflow(),
        "savings_rate_trend": _savings_rate_trend(monthly_summary),
        "top_creditors": _top_counterparties(load_debts(), "creditor"),
        "top_debtors": _top_counterparties(load_receivables(), "debtor"),
        "recurring_breakdown": _recurring_breakdown(),
    }


def _monthly_income_expenses(df_month: pd.DataFrame) -> list[dict[str, Any]]:
    if df_month is None or df_month.empty:
        return []
    rows = []
    for row in df_month.tail(8).to_dict(orient="records"):
        income = _amount(row.get("income"))
        expenses = _amount(row.get("expenses"))
        total = max(income, expenses, 1.0)
        rows.append({
            "month": str(row.get("month", "")),
            "income": income,
            "expenses": expenses,
            "income_pct": min(100.0, income / total * 100.0),
            "expenses_pct": min(100.0, expenses / total * 100.0),
        })
    return rows


def _category_spending(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df is None or df.empty or "type" not in df.columns:
        return []
    tmp = df.copy()
    tmp["type"] = tmp["type"].fillna("").astype(str).str.casefold()
    tmp = tmp[tmp["type"].eq("expense")]
    if tmp.empty:
        return []
    tmp["amount"] = pd.to_numeric(tmp.get("amount", 0.0), errors="coerce").fillna(0.0).abs()
    tmp["category"] = tmp.get("category", "Uncategorized").fillna("Uncategorized").astype(str).replace("", "Uncategorized")
    grouped = tmp.groupby("category", as_index=False)["amount"].sum().sort_values("amount", ascending=False).head(8)
    total = max(float(grouped["amount"].max() or 0.0), 1.0)
    return [{"category": row["category"], "amount": float(row["amount"]), "pct": min(100.0, float(row["amount"]) / total * 100.0)} for row in grouped.to_dict(orient="records")]


def _account_balance_trend(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df is None or df.empty or "date" not in df.columns:
        return []
    tmp = df.copy()
    tmp["date"] = pd.to_datetime(tmp["date"], errors="coerce")
    tmp = tmp[tmp["date"].notna()].sort_values("date")
    if tmp.empty:
        return []
    if "signed_amount" not in tmp.columns:
        amount = pd.to_numeric(tmp.get("amount", 0.0), errors="coerce").fillna(0.0)
        tx_type = tmp.get("type", "").fillna("").astype(str).str.casefold()
        tmp["signed_amount"] = amount.where(tx_type.eq("income"), -amount)
    tmp["balance"] = pd.to_numeric(tmp["signed_amount"], errors="coerce").fillna(0.0).cumsum()
    sampled = tmp.set_index("date")["balance"].resample("W").last().dropna().tail(10).reset_index()
    if sampled.empty:
        sampled = tmp[["date", "balance"]].tail(10)
    values = sampled["balance"].astype(float)
    min_v = float(values.min())
    max_v = float(values.max())
    span = max(max_v - min_v, 1.0)
    return [{"date": row["date"].strftime("%Y-%m-%d"), "balance": float(row["balance"]), "pct": (float(row["balance"]) - min_v) / span * 100.0} for row in sampled.to_dict(orient="records")]


def _debts_progress() -> list[dict[str, Any]]:
    rows = []
    for debt in load_debts():
        original = _amount(debt.get("original_amount"))
        remaining = _amount(debt.get("remaining_amount"))
        if original <= 0:
            continue
        paid = max(0.0, original - remaining)
        rows.append({
            "name": debt.get("name") or "Debt",
            "counterparty": debt.get("creditor") or "Unknown",
            "remaining": remaining,
            "progress": min(100.0, paid / original * 100.0),
            "status": debt.get("status") or "active",
        })
    rows.sort(key=lambda row: (row["status"] != "active", -row["remaining"]))
    return rows[:8]


def _upcoming_cashflow() -> list[dict[str, Any]]:
    today = date.today()
    horizon = today + timedelta(days=45)
    rows: list[dict[str, Any]] = []
    for pending in load_pending():
        if str(pending.get("status", "pending")).casefold() != "pending":
            continue
        due = _parse_date(pending.get("date_due"))
        if due and today <= due <= horizon:
            direction = "in" if str(pending.get("type", "expense")).casefold() == "income" else "out"
            rows.append(_cashflow_row(due, pending.get("description") or pending.get("category") or "Pending", _amount(pending.get("amount")), direction, "Pending"))
    for payable in load_payables():
        due = _parse_date(payable.get("due_date"))
        if str(payable.get("status", "active")).casefold() == "active" and due and today <= due <= horizon:
            rows.append(_cashflow_row(due, payable.get("name") or "Payable", _amount(payable.get("remaining_amount")), "out", "Payable"))
    for receivable in load_receivables():
        due = _parse_date(receivable.get("due_date"))
        if str(receivable.get("status", "active")).casefold() == "active" and due and today <= due <= horizon:
            rows.append(_cashflow_row(due, receivable.get("name") or "Receivable", _amount(receivable.get("remaining_amount")), "in", "Receivable"))
    try:
        for planned in active_planned_expenses_for_forecast():
            due = _parse_date(planned.get("due_date"))
            if due and today <= due <= horizon:
                rows.append(_cashflow_row(due, planned.get("title") or "Planned expense", _amount(planned.get("remaining_amount") or planned.get("expected_amount")), "out", "Planned"))
    except Exception:
        pass
    rows.sort(key=lambda row: (row["date"], row["direction"] != "out", row["title"]))
    return rows[:12]


def _savings_rate_trend(df_month: pd.DataFrame) -> list[dict[str, Any]]:
    if df_month is None or df_month.empty:
        return []
    rows = []
    for row in df_month.tail(8).to_dict(orient="records"):
        income = _amount(row.get("income"))
        net = _amount(row.get("net"))
        rate = 0.0 if income <= 0 else max(-100.0, min(100.0, net / income * 100.0))
        rows.append({"month": str(row.get("month", "")), "rate": rate, "pct": max(0.0, min(100.0, rate + 50.0))})
    return rows


def _top_counterparties(rows: list[dict], field: str) -> list[dict[str, Any]]:
    totals: dict[str, float] = {}
    for row in rows:
        if str(row.get("status", "active")).casefold() != "active":
            continue
        name = str(row.get(field) or "Unknown").strip() or "Unknown"
        totals[name] = totals.get(name, 0.0) + _amount(row.get("remaining_amount"))
    max_v = max(totals.values(), default=0.0) or 1.0
    result = [{"name": key, "amount": value, "pct": min(100.0, value / max_v * 100.0)} for key, value in totals.items()]
    result.sort(key=lambda row: row["amount"], reverse=True)
    return result[:6]


def _recurring_breakdown() -> list[dict[str, Any]]:
    totals: dict[str, float] = {}
    for row in load_recurring():
        category = str(row.get("category") or row.get("type") or "Recurring").strip() or "Recurring"
        frequency = max(1.0, _amount(row.get("frequency")) or 1.0)
        amount = _amount(row.get("amount")) / frequency
        if str(row.get("type", "expense")).casefold() == "income":
            category = f"Income · {category}"
        totals[category] = totals.get(category, 0.0) + amount
    max_v = max(totals.values(), default=0.0) or 1.0
    rows = [{"category": key, "monthly_amount": value, "pct": min(100.0, value / max_v * 100.0)} for key, value in totals.items()]
    rows.sort(key=lambda row: row["monthly_amount"], reverse=True)
    return rows[:8]


def _cashflow_row(due: date, title: str, amount: float, direction: str, source: str) -> dict[str, Any]:
    return {"date": due.isoformat(), "title": str(title), "amount": float(amount), "direction": direction, "source": source}


def _parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _amount(value: Any) -> float:
    try:
        return max(0.0, float(str(value or 0).replace(",", ".")))
    except (TypeError, ValueError):
        return 0.0
