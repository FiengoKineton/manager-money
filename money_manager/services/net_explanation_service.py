"""Read-only explanations for the money-position numbers.

The goal is transparency, not new accounting.  This module reuses the existing
``overview_service`` and transaction/account services so the values shown here
stay identical to the rest of the app.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from money_manager.services.account_service import main_account_transactions
from money_manager.services.overview_service import build_overview_context
from money_manager.services.transaction_service import load_transactions, prepare_transactions_for_display
from money_manager.utils.stats import summary_totals


MAX_EXPLANATION_ROWS = 80


def build_net_explanation_context() -> dict[str, Any]:
    """Build a read-only explanation for the current overview balances."""
    overview = build_overview_context()
    all_transactions = load_transactions()
    main_transactions = main_account_transactions(all_transactions)
    main_totals = summary_totals(main_transactions)

    return {
        "overview": overview,
        "headline": _headline_rows(overview),
        "formulas": _formula_rows(overview),
        "main_totals": main_totals,
        "counted_rows": _display_rows(main_transactions, limit=MAX_EXPLANATION_ROWS),
        "excluded_rows": _display_rows(_excluded_liquid_account_rows(all_transactions), limit=MAX_EXPLANATION_ROWS),
        "counted_count": int(len(main_transactions)),
        "excluded_count": int(len(_excluded_liquid_account_rows(all_transactions))),
        "notes": _notes(),
    }


def _headline_rows(overview: dict[str, Any]) -> list[dict[str, Any]]:
    totals = overview["totals"]
    return [
        {
            "label": "Main bank net",
            "value": totals["net"],
            "caption": "Same value used in the top bar and overview. It is not changed by this page.",
        },
        {
            "label": "Visible liquidity",
            "value": overview["combined_visible_liquidity"],
            "caption": "Main bank net + separate liquid-account balances.",
        },
        {
            "label": "Main available position",
            "value": overview["cash_position"],
            "caption": "Visible liquidity + invested capital, excluding market profit/loss.",
        },
        {
            "label": "Adjusted stress position",
            "value": overview["adjusted_stress_position"],
            "caption": "Stress position + recoverable receivables + investment profit/loss.",
        },
    ]


def _formula_rows(overview: dict[str, Any]) -> list[dict[str, Any]]:
    totals = overview["totals"]
    aux = overview["auxiliary_balance"]
    visible = overview["combined_visible_liquidity"]
    invested = overview["investment_capital"]
    credit_pending = overview["credit_pending_amount"]
    active_debt = overview["active_debt"]
    receivable = overview["receivable_active_remaining"]
    pnl = overview["investment_profit_loss"]

    return [
        {
            "name": "Main bank net",
            "formula": "income - expenses - non-dividend investments ± internal transfers",
            "parts": [
                _part("Income", totals["income"]),
                _part("Expenses", -totals["expenses"]),
                _part("Investments", -totals["investments"]),
            ],
            "result": totals["net"],
        },
        {
            "name": "Visible liquidity",
            "formula": "main bank net + separate liquid accounts",
            "parts": [_part("Main bank net", totals["net"]), _part("Separate liquid accounts", aux)],
            "result": visible,
        },
        {
            "name": "Main available position",
            "formula": "visible liquidity + invested capital",
            "parts": [_part("Visible liquidity", visible), _part("Invested capital", invested)],
            "result": overview["cash_position"],
        },
        {
            "name": "Stress position",
            "formula": "main available position - credit pending - active debts",
            "parts": [
                _part("Main available position", overview["cash_position"]),
                _part("Credit pending", -credit_pending),
                _part("Active debts", -active_debt),
            ],
            "result": overview["stress_position"],
        },
        {
            "name": "Adjusted stress position",
            "formula": "stress position + money owed to me + investment profit/loss",
            "parts": [
                _part("Stress position", overview["stress_position"]),
                _part("Money owed to me", receivable),
                _part("Investment profit/loss", pnl),
            ],
            "result": overview["adjusted_stress_position"],
        },
    ]


def _part(label: str, value: float) -> dict[str, Any]:
    return {"label": label, "value": float(value or 0.0)}


def _excluded_liquid_account_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Rows that are not part of the conservative main-bank net.

    This is intentionally explanatory.  It does not decide balances itself; the
    actual values above come from the existing overview/account services.
    """
    if df.empty:
        return df.copy()
    if "is_auxiliary_account" not in df.columns:
        return df.iloc[0:0].copy()
    excluded = df[df["is_auxiliary_account"].fillna(False)].copy()
    return excluded


def _display_rows(df: pd.DataFrame, *, limit: int) -> list[dict[str, Any]]:
    if df.empty:
        return []
    display = prepare_transactions_for_display(df.head(limit).copy())
    for column in ["category", "sub_category", "account", "account_label", "description", "type"]:
        if column not in display.columns:
            display[column] = ""
        display[column] = display[column].fillna("")
    records = display.to_dict(orient="records")
    for row in records:
        row["signed_amount_str"] = f"{float(row.get('signed_amount', 0.0) or 0.0):.2f}"
        row["account_display"] = row.get("account_label") or row.get("account") or "Main bank"
    return records


def _notes() -> list[str]:
    return [
        "This page is read-only and reuses the same overview calculations already used by the app.",
        "Separate liquid-account rows are shown to explain why they are not part of the conservative main-bank net.",
        "Internal-transfer effects are included through the existing main_account_transactions service, so the result matches the top bar.",
    ]
