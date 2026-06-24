from __future__ import annotations

import hashlib
from datetime import date
from typing import Any

import pandas as pd

from money_manager.cache.cache_manager import get_or_compute
from money_manager.services.account_scope_service import transactions_for_scope
from money_manager.utils.stats import expenses_by_category, monthly_summary, summary_totals

TRANSACTION_WINDOW_MONTHS = 2


def rolling_transaction_window(today: date | None = None) -> dict[str, Any]:
    """Return the fast working window used by heavy transaction pages.

    The window starts on the first day of the previous month. Rows before this
    date are treated as an initial condition for balances/cumulative plots, not
    as rows that must be regrouped on every route change.
    """
    today = today or date.today()
    first_this_month = date(today.year, today.month, 1)
    if first_this_month.month == 1:
        first_previous_month = date(first_this_month.year - 1, 12, 1)
    else:
        first_previous_month = date(first_this_month.year, first_this_month.month - 1, 1)
    return {
        "start": first_previous_month.isoformat(),
        "end": today.isoformat(),
        "label": "previous month + current month",
        "months": TRANSACTION_WINDOW_MONTHS,
    }


def transaction_default_date_range() -> tuple[str, str]:
    window = rolling_transaction_window()
    return str(window["start"]), str(window["end"])


def split_scoped_transactions(
    df: pd.DataFrame,
    scope: str | dict[str, Any] | None = "global",
    *,
    start: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    start = start or rolling_transaction_window()["start"]
    scoped = transactions_for_scope(df, scope, user_id=user_id)
    old, recent = split_transactions_at(scoped, start)
    initial = transaction_initial_conditions_for_frame(old, scope=scope, start=start, user_id=user_id)
    return {
        "scope": scope,
        "start": start,
        "full": scoped,
        "historical": old,
        "recent": recent,
        "initial": initial,
        "uses_initial_conditions": True,
    }


def split_transactions_at(df: pd.DataFrame, start: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    if df is None or df.empty or "date" not in df.columns:
        empty = pd.DataFrame() if df is None else df.iloc[0:0].copy()
        return empty, empty
    data = df.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    start_dt = pd.to_datetime(start, errors="coerce")
    if pd.isna(start_dt):
        return data.iloc[0:0].copy(), data.copy()
    dated = data[data["date"].notna()].copy()
    historical = dated[dated["date"] < start_dt].copy()
    recent = dated[dated["date"] >= start_dt].copy()
    return historical, recent


def transaction_initial_conditions_for_frame(
    historical_df: pd.DataFrame,
    *,
    scope: str | dict[str, Any] | None = "global",
    start: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    start = start or rolling_transaction_window()["start"]
    digest = dataframe_digest(historical_df)
    scope_key = _scope_cache_key(scope)

    def _builder() -> dict[str, Any]:
        return _build_initial_conditions(historical_df, scope=scope_key, start=start, digest=digest)

    return get_or_compute(
        "transaction_initial_conditions",
        _builder,
        params={"scope": scope_key, "start": start},
        user_id=user_id,
        extra_fingerprint={"historical_rows_digest": digest, "start": start, "scope": scope_key},
        allow_stale_on_error=True,
    )


def totals_with_initial_conditions(recent_df: pd.DataFrame, initial: dict[str, Any] | None = None) -> dict[str, Any]:
    totals = summary_totals(recent_df) if recent_df is not None and not recent_df.empty else summary_totals(_empty_transactions_frame())
    initial = initial or {}
    opening_net = float(initial.get("opening_net", 0.0) or 0.0)
    totals["opening_net"] = opening_net
    totals["recent_net"] = float(totals.get("net", 0.0) or 0.0)
    totals["net"] = float(totals["recent_net"] + opening_net)
    totals["total_availability"] = float(totals.get("total_availability", 0.0) or 0.0) + opening_net
    income = float(totals.get("income", 0.0) or 0.0)
    totals["savings_rate"] = float(max(totals["recent_net"], 0.0) / income * 100.0) if income > 1e-9 else 0.0
    return totals


def dataframe_digest(df: pd.DataFrame | None) -> str:
    if df is None or df.empty:
        return "empty"
    columns = [
        "id",
        "transaction_uid",
        "type",
        "date",
        "amount",
        "signed_amount",
        "account",
        "account_id",
        "account_key",
        "payment_method_id",
        "category",
        "sub_category",
        "created_at",
    ]
    available = [column for column in columns if column in df.columns]
    data = df[available].copy() if available else df.copy()
    for column in data.columns:
        if pd.api.types.is_datetime64_any_dtype(data[column]):
            data[column] = pd.to_datetime(data[column], errors="coerce").dt.strftime("%Y-%m-%dT%H:%M:%S")
        else:
            data[column] = data[column].fillna("").astype(str)
    sort_columns = [column for column in ["date", "type", "id", "transaction_uid"] if column in data.columns]
    if sort_columns:
        data = data.sort_values(by=sort_columns, kind="stable")
    payload = data.to_csv(index=False).encode("utf-8", errors="ignore")
    return hashlib.sha256(payload).hexdigest()


def _build_initial_conditions(historical_df: pd.DataFrame, *, scope: str, start: str, digest: str) -> dict[str, Any]:
    historical_df = historical_df.copy() if historical_df is not None else _empty_transactions_frame()
    totals = summary_totals(historical_df) if not historical_df.empty else summary_totals(_empty_transactions_frame())
    month_rows = monthly_summary(historical_df).to_dict(orient="records") if not historical_df.empty else []
    category_rows = expenses_by_category(historical_df).to_dict(orient="records") if not historical_df.empty else []
    opening_net = float(totals.get("net", 0.0) or 0.0)
    return {
        "scope": scope,
        "start": start,
        "historical_digest": digest,
        "historical_rows": int(len(historical_df)),
        "opening_net": opening_net,
        "totals": totals,
        "monthly_summary": month_rows,
        "category_summary": category_rows,
        "label": f"Initial condition before {start}",
    }


def _empty_transactions_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=["type", "signed_amount", "amount", "date", "category"])


def _scope_cache_key(scope: str | dict[str, Any] | None) -> str:
    if isinstance(scope, dict):
        return str(scope.get("scope") or scope.get("account_id") or "global")
    return str(scope or "global")
