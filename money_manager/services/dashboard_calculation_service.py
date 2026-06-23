from __future__ import annotations

from datetime import date
from typing import Any

from money_manager.services.calculation_service import cached_context


def get_dashboard_overview_uncached(month: str | None = None, scope: str = "global") -> dict[str, Any]:
    from money_manager.services.overview_service import build_overview_context

    return build_overview_context(scope=scope)


def get_dashboard_overview_cached(month: str | None = None, scope: str = "global") -> dict[str, Any]:
    month = month or date.today().strftime("%Y-%m")
    return cached_context("dashboard_overview", lambda: get_dashboard_overview_uncached(month, scope=scope), params={"month": month, "scope": scope})


def get_quick_overview_uncached() -> dict[str, Any]:
    from money_manager.services.account_scope_service import global_balance_summary

    summary = global_balance_summary()
    net_worth = float(summary.get("net_balance", 0.0) or 0.0)
    auxiliary = 0.0
    pending = float(summary.get("pending_total", 0.0) or 0.0)
    return {
        "net_worth": net_worth,
        "available_cash": net_worth + auxiliary - pending,
        "auxiliary_total": auxiliary,
        "pending_total": pending,
    }


def get_quick_overview_cached() -> dict[str, Any]:
    return cached_context("quick_overview", get_quick_overview_uncached, params={})


def get_net_worth_cached(as_of: str | None = None) -> float:
    return float(get_quick_overview_cached().get("net_worth", 0.0) or 0.0)


def get_available_cash_cached(as_of: str | None = None) -> float:
    return float(get_quick_overview_cached().get("available_cash", 0.0) or 0.0)
