from __future__ import annotations

from datetime import date

import pandas as pd

from money_manager.config import default_date_range
from money_manager.repositories.pending import load_pending
from money_manager.services.analytics_service import period_summaries
from money_manager.services.debt_service import page_context as debt_page_context
from money_manager.services.parent_support_service import overview_totals as parent_support_totals
from money_manager.services.pending_service import pending_total
from money_manager.services.sparagnat_service import overview_totals as sparagnat_overview_totals
from money_manager.services.transaction_service import load_transactions
from money_manager.utils.stats import expenses_by_category, summary_totals


def build_overview_context() -> dict:
    start_default, end_default = default_date_range()
    transactions = load_transactions()
    totals = summary_totals(transactions)
    stats_this_month, stats_3_months = period_summaries(transactions)

    pending_rows = load_pending()
    pending_amount = pending_total(pending_rows)
    debt_context = debt_page_context()
    sparagnat_context = sparagnat_overview_totals(start_default, end_default)
    parent_context = parent_support_totals(start_default, end_default)

    saved_expenses = sparagnat_context["saved_expenses"]
    cash_collected = sparagnat_context["cash_collected"]
    active_debt = debt_context["totals"]["active_remaining"]
    parent_total = parent_context["total_support"]

    top_categories = expenses_by_category(transactions).head(5).to_dict(orient="records")
    recent_transactions = _recent_transactions(transactions, limit=8)

    cash_position = totals["net"] + totals["investments"]
    stress_position = cash_position - pending_amount - active_debt

    return {
        "today": date.today().isoformat(),
        "period": {"start": start_default, "end": end_default},
        "totals": totals,
        "stats_this_month": stats_this_month,
        "stats_3_months": stats_3_months,
        "pending_amount": pending_amount,
        "active_debt": active_debt,
        "pending_debt_payments": debt_context["totals"]["pending_debt_payments"],
        "saved_expenses": saved_expenses,
        "cash_collected": cash_collected,
        "net_if_you_paid_saved_expenses": totals["net"] - saved_expenses,
        "parent_support": parent_context,
        "parent_support_total": parent_total,
        "cash_position": cash_position,
        "stress_position": stress_position,
        "top_categories": top_categories,
        "recent_transactions": recent_transactions,
        "quick_health": _health_cards(totals, pending_amount, active_debt, parent_total),
    }


def _recent_transactions(df: pd.DataFrame, limit: int = 8) -> list[dict]:
    if df.empty:
        return []

    display = df.head(limit).copy()
    display["date_str"] = display["date"].dt.strftime("%Y-%m-%d")
    display["amount_str"] = display["amount"].map(lambda value: f"{value:.2f}")
    display["description"] = display["description"].fillna("")
    display["account"] = display["account"].fillna("")
    return display.to_dict(orient="records")


def _health_cards(totals: dict, pending_amount: float, active_debt: float, parent_total: float) -> list[dict]:
    net = totals["net"]
    income = totals["income"]
    expenses = totals["expenses"]
    savings_rate = totals["savings_rate"]

    cards = []

    if net >= 0:
        cards.append({
            "label": "Cash flow",
            "value": "Positive",
            "tone": "good",
            "text": f"Net is positive by €{net:.2f} in the selected default period.",
        })
    else:
        cards.append({
            "label": "Cash flow",
            "value": "Negative",
            "tone": "bad",
            "text": f"You spent €{abs(net):.2f} more than you earned in the selected default period.",
        })

    if active_debt > 0:
        cards.append({
            "label": "Debt exposure",
            "value": f"€{active_debt:.2f}",
            "tone": "warning",
            "text": "This is still open and should be considered before treating the net as usable money.",
        })
    else:
        cards.append({
            "label": "Debt exposure",
            "value": "Clean",
            "tone": "good",
            "text": "No active debt is currently tracked.",
        })

    if pending_amount > 0:
        cards.append({
            "label": "Pending this month",
            "value": f"€{pending_amount:.2f}",
            "tone": "warning",
            "text": "This amount is already expected to leave your balance.",
        })

    if income > 0 and expenses / income > 0.80:
        cards.append({
            "label": "Spending pressure",
            "value": f"{expenses / income * 100:.0f}%",
            "tone": "warning",
            "text": "Expenses are taking a large part of income. Watch the next few weeks carefully.",
        })
    else:
        cards.append({
            "label": "Savings rate",
            "value": f"{savings_rate:.1f}%",
            "tone": "good" if savings_rate >= 20 else "neutral",
            "text": "This is calculated from the real transaction net, not from support trackers.",
        })

    if parent_total > 0:
        cards.append({
            "label": "Parent support",
            "value": f"€{parent_total:.2f}",
            "tone": "neutral",
            "text": "Tracked separately from real income, so your dashboard stays honest.",
        })

    return cards[:5]
