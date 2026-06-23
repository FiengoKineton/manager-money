from __future__ import annotations

from datetime import date

import pandas as pd

from money_manager.config import CREDIT_ACCOUNT_KEYWORDS, default_date_range
from money_manager.repositories.pending import load_pending
from money_manager.services.analytics_service import period_summaries
from money_manager.services.debt_service import page_context as debt_page_context
from money_manager.services.investment_service import overview_snapshot as investment_overview_snapshot
from money_manager.services.parent_support_service import overview_totals as parent_support_totals
from money_manager.services.receivable_service import overview_totals as receivable_overview_totals
from money_manager.services.sparagnat_service import overview_totals as sparagnat_overview_totals
from money_manager.services.transaction_service import load_transactions
from money_manager.utils.filters import filter_by_date
from money_manager.utils.stats import expenses_by_category, summary_totals
from money_manager.services.account_scope_service import (
    all_financial_center_summaries,
    global_balance_summary,
    pending_total_for_scope,
    scope_balance_summary,
    transactions_for_scope,
)


def build_overview_context(scope: str = "global") -> dict:
    from money_manager.services.cache_service import cached_calculation

    return cached_calculation(
        "overview.context",
        lambda: _build_overview_context_uncached(scope=scope),
        extra_fingerprint={"scope": str(scope or "global")},
    )


def _build_overview_context_uncached(scope: str = "global") -> dict:
    # The visible log/chart period starts on January 1st of the current year.
    # Money position, balances, stress, and available cash are calculated from
    # the full CSV history so opening/older rows still count.
    start_default, end_default = default_date_range()
    transactions = load_transactions()
    selected_scope = scope or "global"
    main_transactions_all = transactions_for_scope(transactions, selected_scope)
    main_transactions_display = filter_by_date(main_transactions_all, start_default, end_default)
    scope_summary = scope_balance_summary(selected_scope)
    global_summary = global_balance_summary()
    totals = summary_totals(main_transactions_all)
    totals["net"] = scope_summary.get("net_balance", totals.get("net", 0.0))
    display_totals = summary_totals(main_transactions_display)
    stats_this_month, stats_3_months = period_summaries(main_transactions_all)

    pending_rows = load_pending()
    pending_amount = pending_total_for_scope(selected_scope)
    debt_context = debt_page_context()
    sparagnat_context = sparagnat_overview_totals()
    parent_context = parent_support_totals()
    receivable_context = receivable_overview_totals()
    investment_context = investment_overview_snapshot(refresh=False)

    is_account_scope = str(scope_summary.get("kind") or "") == "account" or str(selected_scope).startswith("account:")

    saved_expenses = sparagnat_context["saved_expenses"] if not is_account_scope else 0.0
    cash_collected = sparagnat_context["cash_collected"] if not is_account_scope else 0.0
    active_debt = debt_context["totals"]["active_remaining"] if not is_account_scope else float(scope_summary.get("payables_total", 0.0) or 0.0)
    parent_total = parent_context["total_support"] if not is_account_scope else 0.0

    auxiliary_accounts = all_financial_center_summaries()
    auxiliary_balance = 0.0 if is_account_scope else max(0.0, float(global_summary.get("net_balance", 0.0)) - float(scope_summary.get("net_balance", 0.0)))

    top_categories = expenses_by_category(main_transactions_display).head(5).to_dict(orient="records")
    recent_transactions = _recent_transactions(main_transactions_display, limit=8)

    # Key money definitions, all based on full history.
    # In global scope this is the total across all Conti.
    # In account scope this is strictly the selected account/Conto net, so opening
    # Bank2 never keeps showing the All Conti value.
    all_accounts_net = float(scope_summary.get("net_balance", totals.get("net", 0.0)) or 0.0) if is_account_scope else float(global_summary.get("net_balance", totals["net"] + auxiliary_balance))
    credit_pending_amount = float(pending_amount if is_account_scope else _credit_pending_total(pending_rows))
    investment_capital = 0.0 if is_account_scope else investment_context["net_invested"]
    investment_profit_loss = 0.0 if is_account_scope else investment_context["profit_loss"]
    receivable_active_remaining = 0.0 if is_account_scope else receivable_context["active_remaining"]
    cash_position = all_accounts_net + investment_capital
    stress_position = cash_position - credit_pending_amount - active_debt
    adjusted_stress_position = stress_position + receivable_active_remaining + investment_profit_loss
    visible_liquidity = all_accounts_net
    market_adjusted_position = cash_position + investment_profit_loss

    return {
        "today": date.today().isoformat(),
        "period": {"start": start_default, "end": end_default},
        "totals": totals,
        "display_totals": display_totals,
        "stats_this_month": stats_this_month,
        "stats_3_months": stats_3_months,
        "pending_amount": pending_amount,
        "credit_pending_amount": credit_pending_amount,
        "active_debt": active_debt,
        "pending_debt_payments": debt_context["totals"]["pending_debt_payments"],
        "saved_expenses": saved_expenses,
        "cash_collected": cash_collected,
        "net_if_you_paid_saved_expenses": totals["net"] - saved_expenses,
        "parent_support": parent_context,
        "parent_support_total": parent_total,
        "receivables": receivable_context,
        "receivable_active_remaining": receivable_active_remaining,
        "net_if_receivables_repaid": totals["net"] + receivable_active_remaining,
        "visible_if_receivables_repaid": visible_liquidity + receivable_active_remaining,
        "investment_overview": investment_context,
        "investment_capital": investment_capital,
        "investment_profit_loss": investment_profit_loss,
        "investment_profit_loss_pct": investment_context["profit_loss_pct"],
        "investment_estimated_value": investment_context["estimated_value"],
        "all_accounts_net": all_accounts_net,
        "cash_position": cash_position,
        "main_available_position": cash_position,
        "market_adjusted_position": market_adjusted_position,
        "total_financial_position": market_adjusted_position,
        "stress_position": stress_position,
        "adjusted_stress_position": adjusted_stress_position,
        "main_transactions_count": int(len(main_transactions_display)),
        "selected_scope": selected_scope,
        "is_account_scope": is_account_scope,
        "is_global_scope": not is_account_scope,
        "scope_summary": scope_summary,
        "global_summary": global_summary,
        "auxiliary_accounts": auxiliary_accounts,
        "auxiliary_balance": auxiliary_balance,
        "combined_visible_liquidity": visible_liquidity,
        "liquidity_snapshot": _liquidity_snapshot(cash_position, visible_liquidity, credit_pending_amount, active_debt, adjusted_stress_position),
        "top_categories": top_categories,
        "recent_transactions": recent_transactions,
        "quick_health": _health_cards(totals, credit_pending_amount, active_debt, parent_total),
    }


def _credit_pending_total(rows: list[dict]) -> float:
    """Open credit-account/credit-route expenses still expected to leave main."""
    from money_manager.services.pending_service import CREDIT_STATEMENT_SOURCE, _credit_pending_key

    total = 0.0
    for row in rows:
        if str(row.get("status", "pending")).lower() != "pending":
            continue
        if str(row.get("type", "expense")).lower() == "income":
            continue
        account_value = str(row.get("account", "")).strip().casefold()
        is_credit_statement = row.get("source") == CREDIT_STATEMENT_SOURCE
        is_credit_route = bool(_credit_pending_key(account_value) or _credit_pending_key(row.get("account_key", "")))
        if not (is_credit_statement or is_credit_route or account_value in CREDIT_ACCOUNT_KEYWORDS):
            continue
        try:
            total += float(row.get("amount", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
    return float(total)


def _liquidity_snapshot(cash_position: float, visible_liquidity: float, credit_pending: float, active_debt: float, adjusted_stress: float) -> list[dict]:
    return [
        {
            "label": "Available",
            "value": cash_position,
            "caption": "Selected/global account net + invested capital",
            "tone": "main",
        },
        {
            "label": "Visible liquidity",
            "value": visible_liquidity,
            "caption": "Scoped liquidity without duplicate dependent accounts",
            "tone": "aux",
        },
        {
            "label": "Committed credit/debt",
            "value": credit_pending + active_debt,
            "caption": "Credit/pending payments plus active debts",
            "tone": "warning",
        },
        {
            "label": "Adjusted stress",
            "value": adjusted_stress,
            "caption": "Stress + owed to me + market P/L",
            "tone": "total",
        },
    ]


def _recent_transactions(df: pd.DataFrame, limit: int = 8) -> list[dict]:
    if df.empty:
        return []

    display = df.head(limit).copy()
    display["date_str"] = display["date"].dt.strftime("%Y-%m-%d")
    display["amount_str"] = display["amount"].map(lambda value: f"{value:.2f}")
    display["description"] = display["description"].fillna("")
    display["account"] = display["account"].fillna("")
    if "account_label" not in display.columns:
        display["account_label"] = display["account"]
    if "is_auxiliary_account" not in display.columns:
        display["is_auxiliary_account"] = False
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
            "label": "Credit pressure",
            "value": f"€{pending_amount:.2f}",
            "tone": "warning",
            "text": "This credit/pending amount is already expected to leave your balance.",
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
