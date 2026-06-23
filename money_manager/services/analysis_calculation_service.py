from __future__ import annotations

from datetime import date
from typing import Any

from money_manager.services.calculation_service import cached_context


def get_monthly_summary_uncached(year: int | str | None = None, scope: str = "global") -> list[dict[str, Any]]:
    from money_manager.services.account_scope_service import transactions_for_scope
    from money_manager.services.transaction_service import load_transactions
    from money_manager.utils.stats import monthly_summary

    df = transactions_for_scope(load_transactions(), scope)
    if year:
        start = f"{int(year):04d}-01-01"
        end = f"{int(year):04d}-12-31"
        result = monthly_summary(df, start=start, end=end)
    else:
        result = monthly_summary(df)
    return result.to_dict(orient="records") if hasattr(result, "to_dict") else []


def get_monthly_summary_cached(year: int | str | None = None, scope: str = "global") -> list[dict[str, Any]]:
    return cached_context("monthly_summary", lambda: get_monthly_summary_uncached(year=year, scope=scope), params={"year": year or "all", "scope": scope})


def get_category_summary_uncached(month: str | None = None, account_id: str | None = None, payment_method_id: str | None = None, scope: str = "global", **kwargs) -> list[dict[str, Any]]:
    from money_manager.services.account_scope_service import transactions_for_scope
    from money_manager.services.transaction_service import load_transactions
    from money_manager.utils.stats import expenses_by_category

    df = transactions_for_scope(load_transactions(), scope)
    if month and "date" in df.columns:
        df = df[df["date"].astype(str).str.startswith(month)]
    if account_id and "account_id" in df.columns:
        df = df[df["account_id"].astype(str) == str(account_id)]
    if payment_method_id and "payment_method_id" in df.columns:
        df = df[df["payment_method_id"].astype(str) == str(payment_method_id)]
    result = expenses_by_category(df)
    return result.to_dict(orient="records") if hasattr(result, "to_dict") else []


def get_category_summary_cached(month: str | None = None, account_id: str | None = None, payment_method_id: str | None = None, scope: str = "global") -> list[dict[str, Any]]:
    return cached_context("category_summary", lambda: get_category_summary_uncached(month, account_id, payment_method_id, scope=scope), params={"month": month, "account_id": account_id, "payment_method_id": payment_method_id, "scope": scope})


def get_payment_method_breakdown_uncached(month: str | None = None, scope: str = "global", **kwargs) -> list[dict[str, Any]]:
    from money_manager.services.account_calculation_service import get_payment_method_summary_uncached

    return list(get_payment_method_summary_uncached(month=month, scope=scope).get("methods", []))


def get_payment_method_breakdown_cached(month: str | None = None, scope: str = "global") -> list[dict[str, Any]]:
    month = month or date.today().strftime("%Y-%m")
    return cached_context("payment_method_breakdown", lambda: get_payment_method_breakdown_uncached(month, scope=scope), params={"month": month, "scope": scope})


def get_account_breakdown_uncached(month: str | None = None, scope: str = "global", **kwargs) -> list[dict[str, Any]]:
    from money_manager.services.account_scope_service import all_financial_center_summaries, scope_balance_summary

    if scope and scope != "global":
        return [scope_balance_summary(scope)]
    return all_financial_center_summaries()


def get_account_breakdown_cached(month: str | None = None, scope: str = "global") -> list[dict[str, Any]]:
    month = month or date.today().strftime("%Y-%m")
    return cached_context("account_breakdown", lambda: get_account_breakdown_uncached(month, scope=scope), params={"month": month, "scope": scope})


def get_yearly_summary_uncached(year: int | str | None = None) -> dict[str, Any]:
    from money_manager.services.yearly_summary_service import build_yearly_summary_context

    return build_yearly_summary_context(year)


def get_yearly_summary_cached(year: int | str | None = None) -> dict[str, Any]:
    selected = year or date.today().year
    return cached_context("yearly_summary", lambda: get_yearly_summary_uncached(selected), params={"year": selected})


def get_analysis_metrics_cached(period_key: str = "ytd", scope: str = "global") -> dict[str, Any]:
    from money_manager.services.analytics_service import build_analysis_metrics
    from money_manager.services.transaction_service import load_transactions

    return cached_context("analysis_metrics", lambda: build_analysis_metrics(load_transactions(), period_key=period_key, scope=scope), params={"period": period_key, "scope": scope})
