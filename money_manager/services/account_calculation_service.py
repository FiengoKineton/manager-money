from __future__ import annotations

from datetime import date
from typing import Any

from money_manager.services.calculation_service import cached_context


def get_account_balances_uncached(as_of: str | None = None, include_scheduled: bool = False, scope: str = "global") -> list[dict[str, Any]]:
    from money_manager.services.account_scope_service import all_financial_center_summaries, scope_balance_summary

    if scope and scope != "global":
        return [scope_balance_summary(scope)]
    return all_financial_center_summaries()


def get_account_balances_cached(as_of: str | None = None, include_scheduled: bool = False, scope: str = "global") -> list[dict[str, Any]]:
    as_of = as_of or date.today().isoformat()
    return cached_context(
        "account_balances",
        lambda: get_account_balances_uncached(as_of=as_of, include_scheduled=include_scheduled, scope=scope),
        params={"as_of": as_of, "include_scheduled": bool(include_scheduled), "scope": scope},
    )


def get_account_dashboard_summary_uncached(month: str | None = None) -> dict[str, Any]:
    from money_manager.services.account_service import accounts_page_context
    from money_manager.services.transaction_service import load_transactions

    return accounts_page_context(load_transactions())


def get_current_account_summary_cached(month: str | None = None) -> dict[str, Any]:
    summary = get_account_dashboard_summary_cached(month=month)
    accounts = [row for row in summary.get("accounts", []) if row.get("is_current_account")]
    return {"accounts": accounts, "total": float(sum(float(row.get("balance", 0) or 0) for row in accounts))}


def get_dependent_account_summary_cached(parent_account_id: str | None = None) -> dict[str, Any]:
    accounts = get_account_balances_cached()
    filtered = [row for row in accounts if row.get("is_dependent_account") and (not parent_account_id or row.get("parent_account_id") == parent_account_id or row.get("parent_key") == parent_account_id)]
    return {"accounts": filtered, "total": float(sum(float(row.get("balance", 0) or 0) for row in filtered))}


def get_credit_liability_summary_cached(month: str | None = None) -> dict[str, Any]:
    accounts = get_account_balances_cached()
    filtered = [row for row in accounts if row.get("is_liability") or row.get("main_net_policy") == "credit_pending"]
    return {"accounts": filtered, "total": float(sum(float(row.get("balance", 0) or 0) for row in filtered))}


def get_account_dashboard_summary_cached(month: str | None = None) -> dict[str, Any]:
    month = month or date.today().strftime("%Y-%m")
    return cached_context("account_dashboard_summary", lambda: get_account_dashboard_summary_uncached(month=month), params={"month": month})


def get_payment_method_summary_uncached(month: str | None = None, scope: str = "global") -> dict[str, Any]:
    from collections import defaultdict

    from money_manager.services.transaction_service import load_transactions
    from money_manager.services.account_scope_service import transactions_for_scope

    df = transactions_for_scope(load_transactions(), scope)
    rows: list[dict[str, Any]] = []
    if df is not None and not df.empty:
        data = df.copy()
        if month and "date" in data.columns:
            dates = data["date"].astype(str)
            data = data[dates.str.startswith(month)]
        groups: dict[str, dict[str, Any]] = defaultdict(lambda: {"payment_method_id": "", "payment_method": "", "count": 0, "amount": 0.0})
        for _, row in data.iterrows():
            key = str(row.get("payment_method_id") or row.get("payment_method") or "unspecified")
            groups[key]["payment_method_id"] = str(row.get("payment_method_id") or "")
            groups[key]["payment_method"] = str(row.get("payment_method") or key)
            groups[key]["count"] += 1
            try:
                groups[key]["amount"] += abs(float(row.get("amount", 0) or 0))
            except Exception:
                pass
        rows = sorted(groups.values(), key=lambda item: float(item.get("amount", 0.0)), reverse=True)
    return {"methods": rows, "count": len(rows)}


def get_payment_method_summary_cached(month: str | None = None, scope: str = "global") -> dict[str, Any]:
    month = month or date.today().strftime("%Y-%m")
    return cached_context("payment_method_summary", lambda: get_payment_method_summary_uncached(month=month, scope=scope), params={"month": month, "scope": scope})
