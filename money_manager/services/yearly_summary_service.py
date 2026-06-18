from __future__ import annotations

from collections import defaultdict
from datetime import date

import pandas as pd

from money_manager.config import DEBT_PAYMENT_CATEGORY, default_date_range
from money_manager.repositories.debts import load_debts
from money_manager.repositories.internal_transfers import load_rows as load_internal_transfer_rows
from money_manager.repositories.payables import load_payables
from money_manager.repositories.pending import load_pending
from money_manager.repositories.receivables import load_receivables
from money_manager.repositories.recurring import load_recurring
from money_manager.services.account_service import account_movements, main_account_transactions
from money_manager.services.analytics_service import cumulative_balance_with_opening
from money_manager.services.transaction_service import load_transactions
from money_manager.utils.filters import filter_by_date
from money_manager.utils.interactive_plots import (
    chart_cumulative_balance,
    chart_expenses_by_category,
    chart_monthly_summary,
)
from money_manager.utils.stats import expenses_by_category, monthly_summary, summary_totals

RECEIVABLE_EXPENSE_CATEGORY = "Money owed to me"
RECEIVABLE_INCOME_CATEGORY = "Refund"
PAYABLE_DEFAULT_CATEGORY = "Payable"


def build_yearly_summary_context(selected_year: int | str | None = None) -> dict:
    """Build the archive/report page for one selected year.

    The page follows the same principle used by the dashboard: the selected year
    is the visible/reporting window, while the opening balance is calculated from
    full history before January 1st of that year. No artificial year-closing rows
    are written to CSV.
    """
    today = date.today()
    tx_all = load_transactions()
    main_all = main_account_transactions(tx_all)

    years = available_years(tx_all, main_all, today.year)
    year = _coerce_year(selected_year, years, today.year)
    start, end, exclusive_end = _year_window(year, today)

    main_year = _between_dates(main_all, start, exclusive_end)
    tx_year = _between_dates(tx_all, start, exclusive_end)

    opening_net = _signed_sum_before(main_all, start, column="signed_amount")
    closing_net = _signed_sum_before(main_all, exclusive_end, column="signed_amount")
    totals = summary_totals(main_year) if not main_year.empty else _empty_totals()
    totals["opening_net"] = float(opening_net)
    totals["closing_net"] = float(closing_net)
    totals["net_change"] = float(closing_net - opening_net)

    monthly = monthly_summary(main_year, start=start.isoformat(), end=end.isoformat())
    categories = expenses_by_category(main_year).head(10)
    cumulative = cumulative_balance_with_opening(
        main_year,
        start=start.isoformat(),
        opening_source_df=main_all,
        include_opening_balance=True,
    )

    aux = _auxiliary_initial_conditions(tx_all, start, exclusive_end)
    debts = _debt_summary(year, start, exclusive_end, tx_all)
    payables = _payable_summary(year, start, exclusive_end, tx_all)
    receivables = _receivable_summary(year, start, exclusive_end, tx_all)
    recurring = _recurring_summary(year, start, exclusive_end, tx_all)
    income_sources = _income_sources(main_year)
    investment = _investment_summary(tx_year)
    transfers = _internal_transfer_summary(year)

    insight_cards = _year_insights(totals, debts, payables, receivables, recurring)

    return {
        "selected_year": year,
        "current_year": today.year,
        "available_years": years,
        "period": {
            "start": _date_label(start),
            "end": _date_label(end),
            "is_current_year": year == today.year,
            "label": f"{_date_label(start)} → {_date_label(end)}",
        },
        "totals": totals,
        "initial_conditions": {
            "main_net": float(opening_net),
            "closing_net": float(closing_net),
            "auxiliary": aux,
        },
        "debts": debts,
        "payables": payables,
        "receivables": receivables,
        "recurring": recurring,
        "income_sources": income_sources,
        "investment": investment,
        "transfers": transfers,
        "top_categories": categories.to_dict(orient="records"),
        "insight_cards": insight_cards,
        "charts": {
            "monthly_summary": chart_monthly_summary(monthly),
            "expenses_by_category": chart_expenses_by_category(categories),
            "cumulative_balance": chart_cumulative_balance(cumulative),
        },
    }


def available_years(tx_all: pd.DataFrame, main_all: pd.DataFrame, current_year: int | None = None) -> list[int]:
    current_year = current_year or date.today().year
    candidates: list[pd.Timestamp] = []

    for frame in [tx_all, main_all]:
        if frame is not None and not frame.empty and "date" in frame.columns:
            dates = pd.to_datetime(frame["date"], errors="coerce").dropna()
            candidates.extend(dates.tolist())

    for rows, date_fields in [
        (load_pending(), ["date_due"]),
        (load_debts(), ["start_date", "due_date", "closed_at"]),
        (load_payables(), ["start_date", "due_date", "closed_at"]),
        (load_receivables(), ["start_date", "due_date", "closed_at"]),
        (load_recurring(), ["start_date", "end_date", "last_generated"]),
        (load_internal_transfer_rows(), ["date"]),
    ]:
        for row in rows:
            for field in date_fields:
                parsed = _to_timestamp(row.get(field))
                if parsed is not None:
                    candidates.append(parsed)

    if not candidates:
        start_default, _ = default_date_range()
        fallback = _to_timestamp(start_default)
        first_year = fallback.year if fallback is not None else current_year
    else:
        first_year = min(ts.year for ts in candidates)

    first_year = min(first_year, current_year)
    return list(range(first_year, current_year + 1))


def _coerce_year(value: int | str | None, years: list[int], current_year: int) -> int:
    if not years:
        return current_year
    try:
        year = int(value) if value is not None and str(value).strip() else current_year
    except (TypeError, ValueError):
        year = current_year
    return max(min(year, max(years)), min(years))


def _year_window(year: int, today: date) -> tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]:
    start = pd.Timestamp(year=year, month=1, day=1)
    natural_end = pd.Timestamp(year=year, month=12, day=31)
    end = min(natural_end, pd.Timestamp(today)) if year == today.year else natural_end
    exclusive_end = pd.Timestamp(year=year + 1, month=1, day=1)
    if year == today.year:
        exclusive_end = pd.Timestamp(today) + pd.Timedelta(days=1)
    return start, end, exclusive_end


def _between_dates(df: pd.DataFrame, start: pd.Timestamp, exclusive_end: pd.Timestamp) -> pd.DataFrame:
    if df is None or df.empty or "date" not in df.columns:
        return pd.DataFrame(columns=getattr(df, "columns", []))
    dated = df.copy()
    dated["date"] = pd.to_datetime(dated["date"], errors="coerce")
    dated = dated[dated["date"].notna()]
    return dated[(dated["date"] >= start) & (dated["date"] < exclusive_end)].copy()


def _signed_sum_before(df: pd.DataFrame, before: pd.Timestamp, column: str) -> float:
    if df is None or df.empty or "date" not in df.columns or column not in df.columns:
        return 0.0
    dated = df.copy()
    dated["date"] = pd.to_datetime(dated["date"], errors="coerce")
    dated[column] = pd.to_numeric(dated[column], errors="coerce").fillna(0.0)
    dated = dated[dated["date"].notna() & (dated["date"] < before)]
    return float(dated[column].sum())


def _empty_totals() -> dict:
    return {
        "income": 0.0,
        "expenses": 0.0,
        "investments": 0.0,
        "net": 0.0,
        "savings_rate": 0.0,
        "total_availability": 0.0,
    }


def _auxiliary_initial_conditions(tx_all: pd.DataFrame, start: pd.Timestamp, exclusive_end: pd.Timestamp) -> dict:
    movements = account_movements(tx_all)
    if movements.empty:
        return {"opening_total": 0.0, "closing_total": 0.0, "net_change": 0.0, "accounts": []}

    movements = movements.copy()
    movements["date"] = pd.to_datetime(movements["date"], errors="coerce")
    movements["account_signed_amount"] = pd.to_numeric(movements["account_signed_amount"], errors="coerce").fillna(0.0)
    movements = movements[movements["date"].notna()]

    accounts = []
    for account_key, group in movements.groupby("account_key", dropna=False):
        label = _clean(group["account_label"].iloc[0]) or _clean(account_key) or "Account"
        opening = float(group[group["date"] < start]["account_signed_amount"].sum())
        yearly = float(group[(group["date"] >= start) & (group["date"] < exclusive_end)]["account_signed_amount"].sum())
        closing = opening + yearly
        if abs(opening) > 0.005 or abs(yearly) > 0.005 or abs(closing) > 0.005:
            accounts.append({
                "account": label,
                "opening": opening,
                "yearly_change": yearly,
                "closing": closing,
            })

    accounts = sorted(accounts, key=lambda row: abs(row["closing"]), reverse=True)
    opening_total = sum(row["opening"] for row in accounts)
    closing_total = sum(row["closing"] for row in accounts)
    return {
        "opening_total": float(opening_total),
        "closing_total": float(closing_total),
        "net_change": float(closing_total - opening_total),
        "accounts": accounts,
    }


def _debt_summary(year: int, start: pd.Timestamp, exclusive_end: pd.Timestamp, tx_all: pd.DataFrame) -> dict:
    rows = load_debts()
    payments = _between_dates(tx_all, pd.Timestamp.min, exclusive_end)
    if not payments.empty:
        payments = payments[(payments["type"] == "expense") & (payments["category"].astype(str).str.casefold() == DEBT_PAYMENT_CATEGORY.casefold())].copy()

    yearly_paid_rows = _between_dates(payments, start, exclusive_end) if not payments.empty else pd.DataFrame()
    paid_by_name = _amounts_by_label(yearly_paid_rows, prefer="sub_category")
    all_paid_by_name_before_start = _amounts_by_label(_between_dates(payments, pd.Timestamp.min, start) if not payments.empty else pd.DataFrame(), prefer="sub_category")
    all_paid_by_name_until_end = _amounts_by_label(_between_dates(payments, pd.Timestamp.min, exclusive_end) if not payments.empty else pd.DataFrame(), prefer="sub_category")

    touched = []
    created_total = 0.0
    closed_total = 0.0
    by_creditor = defaultdict(lambda: {"creditor": "", "created": 0.0, "paid": 0.0, "remaining_end": 0.0, "count": 0})

    for row in rows:
        name = _clean(row.get("name")) or "Unnamed debt"
        creditor = _clean(row.get("creditor")) or "Unknown creditor"
        original = _money(row.get("original_amount"))
        remaining_current = _money(row.get("remaining_amount"))
        start_date = _to_timestamp(row.get("start_date"))
        closed_at = _to_timestamp(row.get("closed_at"))
        created_this_year = bool(start_date is not None and start_date.year == year)
        closed_this_year = bool(closed_at is not None and closed_at.year == year)
        paid_year = float(paid_by_name.get(name, 0.0))
        paid_before = float(all_paid_by_name_before_start.get(name, 0.0))
        paid_until_end = float(all_paid_by_name_until_end.get(name, 0.0))

        remaining_start = max(0.0, original - paid_before) if original else remaining_current
        if start_date is not None and start_date >= start:
            remaining_start = 0.0
        remaining_end = max(0.0, original - paid_until_end) if original else remaining_current
        if closed_at is not None and closed_at < exclusive_end:
            remaining_end = 0.0

        overlaps = _row_overlaps_period(start_date, closed_at, start, exclusive_end)
        if created_this_year:
            created_total += original
        if closed_this_year:
            closed_total += original

        if overlaps or created_this_year or closed_this_year or paid_year > 0.005:
            touched.append({
                "name": name,
                "party": creditor,
                "original": original,
                "paid_year": paid_year,
                "remaining_start": remaining_start,
                "remaining_end": remaining_end,
                "status": _clean(row.get("status")) or "active",
            })
            bucket = by_creditor[creditor]
            bucket["creditor"] = creditor
            bucket["created"] += original if created_this_year else 0.0
            bucket["paid"] += paid_year
            bucket["remaining_end"] += remaining_end
            bucket["count"] += 1

    return {
        "created_total": float(created_total),
        "paid_total": float(sum(paid_by_name.values())),
        "closed_total": float(closed_total),
        "remaining_start": float(sum(row["remaining_start"] for row in touched)),
        "remaining_end": float(sum(row["remaining_end"] for row in touched)),
        "items": sorted(touched, key=lambda row: row["remaining_end"], reverse=True)[:12],
        "by_party": sorted(by_creditor.values(), key=lambda row: row["remaining_end"], reverse=True)[:8],
    }


def _payable_summary(year: int, start: pd.Timestamp, exclusive_end: pd.Timestamp, tx_all: pd.DataFrame) -> dict:
    return _liability_summary(
        rows=load_payables(),
        tx_all=tx_all,
        start=start,
        exclusive_end=exclusive_end,
        year=year,
        party_field="payee",
        default_party="Unknown payee",
        payment_categories={PAYABLE_DEFAULT_CATEGORY.casefold(), "payable"},
        label="payables",
    )


def _receivable_summary(year: int, start: pd.Timestamp, exclusive_end: pd.Timestamp, tx_all: pd.DataFrame) -> dict:
    rows = load_receivables()
    known_names = {_clean(row.get("name")) for row in rows if _clean(row.get("name"))}
    incomes = _between_dates(tx_all, pd.Timestamp.min, exclusive_end)
    if not incomes.empty:
        sub_categories = incomes.get("sub_category", pd.Series("", index=incomes.index)).fillna("").astype(str)
        descriptions = incomes.get("description", pd.Series("", index=incomes.index)).fillna("").astype(str)
        name_match = sub_categories.isin(known_names)
        if known_names:
            description_match = descriptions.map(lambda text: any(name and name in text for name in known_names))
        else:
            description_match = pd.Series(False, index=incomes.index)
        incomes = incomes[(incomes["type"] == "income") & (name_match | description_match)].copy()
    created_rows = [row for row in rows if (_to_timestamp(row.get("start_date")) is not None and _to_timestamp(row.get("start_date")).year == year)]

    yearly_collected = _between_dates(incomes, start, exclusive_end) if not incomes.empty else pd.DataFrame()
    collected_by_name = _amounts_by_label(yearly_collected, prefer="sub_category")
    collected_before = _amounts_by_label(_between_dates(incomes, pd.Timestamp.min, start) if not incomes.empty else pd.DataFrame(), prefer="sub_category")
    collected_until_end = _amounts_by_label(_between_dates(incomes, pd.Timestamp.min, exclusive_end) if not incomes.empty else pd.DataFrame(), prefer="sub_category")

    touched = []
    by_debtor = defaultdict(lambda: {"debtor": "", "created": 0.0, "collected": 0.0, "remaining_end": 0.0, "count": 0})
    for row in rows:
        name = _clean(row.get("name")) or "Unnamed receivable"
        debtor = _clean(row.get("debtor")) or "Unknown debtor"
        original = _money(row.get("original_amount"))
        remaining_current = _money(row.get("remaining_amount"))
        start_date = _to_timestamp(row.get("start_date"))
        closed_at = _to_timestamp(row.get("closed_at"))
        created_this_year = bool(start_date is not None and start_date.year == year)
        collected_year = float(collected_by_name.get(name, 0.0))
        col_before = float(collected_before.get(name, 0.0))
        col_until_end = float(collected_until_end.get(name, 0.0))
        remaining_start = max(0.0, original - col_before) if original else remaining_current
        if start_date is not None and start_date >= start:
            remaining_start = 0.0
        remaining_end = max(0.0, original - col_until_end) if original else remaining_current
        if closed_at is not None and closed_at < exclusive_end:
            remaining_end = 0.0
        overlaps = _row_overlaps_period(start_date, closed_at, start, exclusive_end)
        if overlaps or created_this_year or collected_year > 0.005:
            touched.append({
                "name": name,
                "party": debtor,
                "original": original,
                "collected_year": collected_year,
                "remaining_start": remaining_start,
                "remaining_end": remaining_end,
                "status": _clean(row.get("status")) or "active",
            })
            bucket = by_debtor[debtor]
            bucket["debtor"] = debtor
            bucket["created"] += original if created_this_year else 0.0
            bucket["collected"] += collected_year
            bucket["remaining_end"] += remaining_end
            bucket["count"] += 1

    return {
        "created_total": float(sum(_money(row.get("original_amount")) for row in created_rows)),
        "collected_total": float(sum(collected_by_name.values())),
        "remaining_start": float(sum(row["remaining_start"] for row in touched)),
        "remaining_end": float(sum(row["remaining_end"] for row in touched)),
        "items": sorted(touched, key=lambda row: row["remaining_end"], reverse=True)[:12],
        "by_party": sorted(by_debtor.values(), key=lambda row: row["remaining_end"], reverse=True)[:8],
    }


def _liability_summary(rows: list[dict], tx_all: pd.DataFrame, start: pd.Timestamp, exclusive_end: pd.Timestamp, year: int, party_field: str, default_party: str, payment_categories: set[str], label: str) -> dict:
    known_names = {_clean(row.get("name")) for row in rows if _clean(row.get("name"))}
    tx_until = _between_dates(tx_all, pd.Timestamp.min, exclusive_end)
    if not tx_until.empty:
        category_match = tx_until["category"].astype(str).str.casefold().isin(payment_categories)
        name_match = tx_until.get("sub_category", pd.Series("", index=tx_until.index)).fillna("").astype(str).isin(known_names)
        tx_until = tx_until[(tx_until["type"] == "expense") & (category_match | name_match)].copy()

    yearly_paid = _between_dates(tx_until, start, exclusive_end) if not tx_until.empty else pd.DataFrame()
    paid_by_name = _amounts_by_label(yearly_paid, prefer="sub_category")
    paid_before = _amounts_by_label(_between_dates(tx_until, pd.Timestamp.min, start) if not tx_until.empty else pd.DataFrame(), prefer="sub_category")
    paid_until = _amounts_by_label(_between_dates(tx_until, pd.Timestamp.min, exclusive_end) if not tx_until.empty else pd.DataFrame(), prefer="sub_category")

    touched = []
    by_party = defaultdict(lambda: {"party": "", "created": 0.0, "paid": 0.0, "remaining_end": 0.0, "count": 0})
    created_total = 0.0
    closed_total = 0.0

    for row in rows:
        name = _clean(row.get("name")) or f"Unnamed {label}"
        party = _clean(row.get(party_field)) or default_party
        original = _money(row.get("original_amount"))
        remaining_current = _money(row.get("remaining_amount"))
        start_date = _to_timestamp(row.get("start_date"))
        closed_at = _to_timestamp(row.get("closed_at"))
        created_this_year = bool(start_date is not None and start_date.year == year)
        closed_this_year = bool(closed_at is not None and closed_at.year == year)
        paid_year = float(paid_by_name.get(name, 0.0))
        remaining_start = max(0.0, original - float(paid_before.get(name, 0.0))) if original else remaining_current
        if start_date is not None and start_date >= start:
            remaining_start = 0.0
        remaining_end = max(0.0, original - float(paid_until.get(name, 0.0))) if original else remaining_current
        if closed_at is not None and closed_at < exclusive_end:
            remaining_end = 0.0

        if created_this_year:
            created_total += original
        if closed_this_year:
            closed_total += original
        overlaps = _row_overlaps_period(start_date, closed_at, start, exclusive_end)
        if overlaps or created_this_year or closed_this_year or paid_year > 0.005:
            touched.append({
                "name": name,
                "party": party,
                "original": original,
                "paid_year": paid_year,
                "remaining_start": remaining_start,
                "remaining_end": remaining_end,
                "status": _clean(row.get("status")) or "active",
            })
            bucket = by_party[party]
            bucket["party"] = party
            bucket["created"] += original if created_this_year else 0.0
            bucket["paid"] += paid_year
            bucket["remaining_end"] += remaining_end
            bucket["count"] += 1

    return {
        "created_total": float(created_total),
        "paid_total": float(sum(paid_by_name.values())),
        "closed_total": float(closed_total),
        "remaining_start": float(sum(row["remaining_start"] for row in touched)),
        "remaining_end": float(sum(row["remaining_end"] for row in touched)),
        "items": sorted(touched, key=lambda row: row["remaining_end"], reverse=True)[:12],
        "by_party": sorted(by_party.values(), key=lambda row: row["remaining_end"], reverse=True)[:8],
    }


def _recurring_summary(year: int, start: pd.Timestamp, exclusive_end: pd.Timestamp, tx_all: pd.DataFrame) -> dict:
    rules = {str(row.get("id", "")): row for row in load_recurring()}
    pending = []
    for row in load_pending():
        if row.get("source") != "recurring":
            continue
        due = _to_timestamp(row.get("date_due"))
        if due is None or not (start <= due < exclusive_end):
            continue
        pending.append(row)

    by_rule: dict[str, dict] = {}
    for row in pending:
        rule_id = str(row.get("source_id", ""))
        rule = rules.get(rule_id, {})
        name = _clean(rule.get("name")) or _clean(row.get("description")) or "Recurring item"
        key = rule_id or name
        item = by_rule.setdefault(key, {
            "name": name,
            "category": _clean(row.get("category")) or _clean(rule.get("category")) or "Recurring",
            "type": _clean(row.get("type")) or _clean(rule.get("type")) or "expense",
            "spent": 0.0,
            "income": 0.0,
            "invested": 0.0,
            "scheduled": 0.0,
            "executed_count": 0,
            "pending_count": 0,
            "status": "active",
        })
        amount = _money(row.get("amount"))
        tx_type = str(row.get("type", "expense")).casefold()
        status = str(row.get("status", "pending")).casefold()
        if status == "executed":
            item["executed_count"] += 1
            if tx_type == "income":
                item["income"] += amount
            elif tx_type == "investment":
                item["invested"] += amount
            else:
                item["spent"] += amount
        else:
            item["pending_count"] += 1
            item["scheduled"] += amount

    # Fallback for older transactions saved before pending rows got source ids.
    if not by_rule and rules:
        tx_year = _between_dates(tx_all, start, exclusive_end)
        for rule_id, rule in rules.items():
            name = _clean(rule.get("name"))
            if not name or tx_year.empty:
                continue
            matched = tx_year[
                (tx_year.get("description", pd.Series(dtype=str)).fillna("").astype(str) == name)
                | (tx_year.get("sub_category", pd.Series(dtype=str)).fillna("").astype(str) == name)
            ]
            if matched.empty:
                continue
            tx_type = _clean(rule.get("type")) or "expense"
            amount = float(pd.to_numeric(matched["amount"], errors="coerce").fillna(0.0).sum())
            by_rule[rule_id] = {
                "name": name,
                "category": _clean(rule.get("category")) or "Recurring",
                "type": tx_type,
                "spent": amount if tx_type == "expense" else 0.0,
                "income": amount if tx_type == "income" else 0.0,
                "invested": amount if tx_type == "investment" else 0.0,
                "scheduled": 0.0,
                "executed_count": int(len(matched)),
                "pending_count": 0,
                "status": "historical",
            }

    items = sorted(by_rule.values(), key=lambda row: (row["spent"] + row["income"] + row["invested"] + row["scheduled"]), reverse=True)
    return {
        "spent_total": float(sum(row["spent"] for row in items)),
        "income_total": float(sum(row["income"] for row in items)),
        "invested_total": float(sum(row["invested"] for row in items)),
        "scheduled_total": float(sum(row["scheduled"] for row in items)),
        "executed_count": int(sum(row["executed_count"] for row in items)),
        "pending_count": int(sum(row["pending_count"] for row in items)),
        "items": items[:12],
    }


def _income_sources(main_year: pd.DataFrame) -> list[dict]:
    if main_year.empty:
        return []
    incomes = main_year[main_year["type"] == "income"].copy()
    if incomes.empty:
        return []
    incomes["source"] = incomes.apply(_source_label, axis=1)
    grouped = incomes.groupby("source", dropna=False).agg(
        total=("signed_amount", "sum"),
        count=("id", "count"),
    ).reset_index()
    grouped["total"] = pd.to_numeric(grouped["total"], errors="coerce").fillna(0.0)
    total_income = float(grouped["total"].sum())
    grouped["share_pct"] = grouped["total"].map(lambda value: 0.0 if total_income <= 0 else float(value) / total_income * 100.0)
    return grouped.sort_values("total", ascending=False).head(12).to_dict(orient="records")


def _investment_summary(tx_year: pd.DataFrame) -> dict:
    inv = tx_year[tx_year["type"] == "investment"].copy() if not tx_year.empty else pd.DataFrame()
    if inv.empty:
        return {"invested_total": 0.0, "dividends": 0.0, "net_flow": 0.0, "count": 0, "by_category": []}
    inv["amount"] = pd.to_numeric(inv["amount"], errors="coerce").fillna(0.0)
    inv["signed_amount"] = pd.to_numeric(inv["signed_amount"], errors="coerce").fillna(0.0)
    category_clean = inv["category"].fillna("").astype(str).str.casefold()
    dividends = float(inv[category_clean.eq("dividend")]["amount"].sum())
    invested = float(inv[~category_clean.eq("dividend")]["amount"].sum())
    net_flow = float(inv["signed_amount"].sum())
    by_category = (
        inv.groupby("category", dropna=False)["amount"]
        .sum()
        .reset_index()
        .rename(columns={"amount": "total"})
        .sort_values("total", ascending=False)
        .head(8)
        .to_dict(orient="records")
    )
    for row in by_category:
        row["category"] = _clean(row.get("category")) or "Uncategorized"
        row["total"] = float(row.get("total", 0.0) or 0.0)
    return {
        "invested_total": invested,
        "dividends": dividends,
        "net_flow": net_flow,
        "count": int(len(inv)),
        "by_category": by_category,
    }


def _internal_transfer_summary(year: int) -> dict:
    rows = []
    total = 0.0
    by_route = defaultdict(lambda: {"route": "", "amount": 0.0, "count": 0})
    for row in load_internal_transfer_rows():
        tx_date = _to_timestamp(row.get("date"))
        if tx_date is None or tx_date.year != year:
            continue
        amount = _money(row.get("amount"))
        total += amount
        route = f"{_clean(row.get('from_account')) or 'Main bank'} → {_clean(row.get('to_account')) or 'Main bank'}"
        rows.append({"date": tx_date.date().isoformat(), "route": route, "amount": amount, "description": _clean(row.get("description"))})
        bucket = by_route[route]
        bucket["route"] = route
        bucket["amount"] += amount
        bucket["count"] += 1
    return {
        "total": float(total),
        "count": len(rows),
        "rows": sorted(rows, key=lambda item: item["date"], reverse=True)[:8],
        "by_route": sorted(by_route.values(), key=lambda item: item["amount"], reverse=True)[:8],
    }


def _year_insights(totals: dict, debts: dict, payables: dict, receivables: dict, recurring: dict) -> list[dict]:
    net_change = float(totals.get("net_change", 0.0))
    savings_rate = float(totals.get("savings_rate", 0.0))
    liability_end = float(debts.get("remaining_end", 0.0)) + float(payables.get("remaining_end", 0.0))
    receivable_end = float(receivables.get("remaining_end", 0.0))
    cards = [
        {
            "label": "Year direction",
            "value": f"€{net_change:.2f}",
            "tone": "good" if net_change >= 0 else "danger",
            "text": "Main-bank movement from the opening balance to the selected year-end.",
        },
        {
            "label": "Savings rate",
            "value": f"{savings_rate:.1f}%",
            "tone": "good" if savings_rate >= 20 else "warning" if savings_rate >= 0 else "danger",
            "text": "Calculated only on income and movements that affect the main net.",
        },
        {
            "label": "Debt + payables left",
            "value": f"€{liability_end:.2f}",
            "tone": "danger" if liability_end > 0 else "good",
            "text": "Estimated end-of-period remaining on tracked debts and payables touched by this year.",
        },
        {
            "label": "Recoverable money",
            "value": f"€{receivable_end:.2f}",
            "tone": "income" if receivable_end > 0 else "neutral",
            "text": "Money still owed to you from receivables active or touched in this year.",
        },
        {
            "label": "Recurring spent",
            "value": f"€{float(recurring.get('spent_total', 0.0)):.2f}",
            "tone": "warning" if float(recurring.get("spent_total", 0.0)) > 0 else "neutral",
            "text": "Executed recurring expense rows in the selected period.",
        },
    ]
    return cards


def _amounts_by_label(df: pd.DataFrame, prefer: str = "sub_category") -> dict[str, float]:
    if df is None or df.empty:
        return {}
    tmp = df.copy()
    tmp["label"] = tmp.apply(lambda row: _source_label(row, prefer=prefer), axis=1)
    tmp["amount"] = pd.to_numeric(tmp["amount"], errors="coerce").fillna(0.0)
    grouped = tmp.groupby("label", dropna=False)["amount"].sum().to_dict()
    return {_clean(key) or "Unlabeled": float(value) for key, value in grouped.items()}


def _source_label(row, prefer: str = "sub_category") -> str:
    fields = [prefer, "description", "category"] if prefer != "description" else ["description", "sub_category", "category"]
    for field in fields:
        value = _clean(row.get(field, ""))
        if value:
            return value
    return "Uncategorized"


def _row_overlaps_period(start_date: pd.Timestamp | None, closed_at: pd.Timestamp | None, start: pd.Timestamp, exclusive_end: pd.Timestamp) -> bool:
    effective_start = start_date or pd.Timestamp.min
    effective_end = closed_at or pd.Timestamp.max
    return effective_start < exclusive_end and effective_end >= start


def _date_label(value: pd.Timestamp) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return ""
    return parsed.date().isoformat()


def _to_timestamp(value) -> pd.Timestamp | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none"}:
        return None
    parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        return None
    try:
        if parsed.year < 1900 or parsed.year > 2200:
            return None
    except Exception:
        return None
    return parsed


def _money(value) -> float:
    try:
        return float(str(value or 0).replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def _clean(value) -> str:
    text = str(value or "").strip()
    if text.casefold() in {"nan", "none", "nat"}:
        return ""
    return text
