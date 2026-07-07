from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Mapping

from money_manager.repositories.debts import load_debt_rules
from money_manager.repositories.expense_projects import load_planned_items
from money_manager.repositories.pending import load_pending
from money_manager.repositories.recurring import normalize_amount, parse_date
from money_manager.services.account_scope_service import (
    debts_for_scope,
    payable_rows_for_scope,
    pending_rows_for_scope,
    receivables_for_scope,
    recurring_rows_for_scope,
)
from money_manager.services.debt_service import next_due_date_for_rule
from money_manager.services.planned_expense_service import active_planned_expenses_for_forecast
from money_manager.services.recurring_service import recurring_forecast_for_period


CALENDAR_EVENT_LIMIT_PER_DAY = 4


def build_financial_calendar_context(
    *,
    selected_scope: Mapping[str, Any] | str | None = None,
    month: str | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    window_start = _parse_month(month, today)
    window_end = date(window_start.year, window_start.month, calendar.monthrange(window_start.year, window_start.month)[1])

    events = build_calendar_events(window_start, window_end, selected_scope=selected_scope, today=today)
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        by_date[event["date"]].append(event)

    for day_events in by_date.values():
        day_events.sort(key=lambda row: (row.get("sort_priority", 50), str(row.get("title", "")).casefold()))

    weeks: list[list[dict[str, Any]]] = []
    first_grid_day = window_start - timedelta(days=window_start.weekday())
    last_grid_day = window_end + timedelta(days=(6 - window_end.weekday()))
    cursor = first_grid_day
    while cursor <= last_grid_day:
        week: list[dict[str, Any]] = []
        for _ in range(7):
            iso = cursor.isoformat()
            day_events = by_date.get(iso, [])
            income_total = sum(float(item.get("amount", 0.0) or 0.0) for item in day_events if item.get("direction") == "in")
            outflow_total = sum(float(item.get("amount", 0.0) or 0.0) for item in day_events if item.get("direction") == "out")
            week.append({
                "date": iso,
                "day": cursor.day,
                "weekday": cursor.strftime("%a"),
                "is_current_month": cursor.month == window_start.month,
                "is_today": cursor == today,
                "events": day_events[:CALENDAR_EVENT_LIMIT_PER_DAY],
                "more_count": max(0, len(day_events) - CALENDAR_EVENT_LIMIT_PER_DAY),
                "income_total": income_total,
                "outflow_total": outflow_total,
                "net_total": income_total - outflow_total,
            })
            cursor += timedelta(days=1)
        weeks.append(week)

    totals_by_kind: dict[str, dict[str, Any]] = {}
    for event in events:
        key = str(event.get("kind") or "other")
        bucket = totals_by_kind.setdefault(key, {
            "kind": key,
            "label": event.get("kind_label", key.replace("_", " ").title()),
            "count": 0,
            "income": 0.0,
            "outflow": 0.0,
        })
        bucket["count"] += 1
        if event.get("direction") == "in":
            bucket["income"] += float(event.get("amount", 0.0) or 0.0)
        else:
            bucket["outflow"] += float(event.get("amount", 0.0) or 0.0)

    timeline = sorted(events, key=lambda row: (row["date"], row.get("sort_priority", 50), row.get("title", "")))
    income = sum(float(item.get("amount", 0.0) or 0.0) for item in events if item.get("direction") == "in")
    outflow = sum(float(item.get("amount", 0.0) or 0.0) for item in events if item.get("direction") == "out")

    prev_start = _add_months(window_start, -1)
    next_start = _add_months(window_start, 1)

    return {
        "calendar_month": window_start.strftime("%Y-%m"),
        "calendar_month_label": window_start.strftime("%B %Y"),
        "calendar_window_start": window_start.isoformat(),
        "calendar_window_end": window_end.isoformat(),
        "calendar_prev_month": prev_start.strftime("%Y-%m"),
        "calendar_next_month": next_start.strftime("%Y-%m"),
        "calendar_today": today.isoformat(),
        "calendar_weeks": weeks,
        "calendar_events": timeline,
        "calendar_totals_by_kind": sorted(totals_by_kind.values(), key=lambda row: (-row["count"], row["label"])),
        "calendar_summary": {
            "income": income,
            "outflow": outflow,
            "net": income - outflow,
            "count": len(events),
        },
    }


def build_calendar_events(
    window_start: date,
    window_end: date,
    *,
    selected_scope: Mapping[str, Any] | str | None = None,
    today: date | None = None,
) -> list[dict[str, Any]]:
    today = today or date.today()
    events: list[dict[str, Any]] = []

    # Recurring rules: salaries, subscriptions, bills and other scheduled items.
    try:
        from money_manager.repositories.recurring import load_recurring

        recurring_rows = recurring_rows_for_scope(load_recurring(), selected_scope)
        recurring_context = recurring_forecast_for_period(window_start, window_end, today=today)
        scoped_ids = {str(row.get("id", "")) for row in recurring_rows}
        scope_limited = _scope_is_limited(selected_scope)
        for item in recurring_context.get("items", []):
            if scope_limited and str(item.get("rule_id", "")) not in scoped_ids:
                continue
            due = _parse_date(item.get("payment_due_date"))
            if not _inside(due, window_start, window_end):
                continue
            tx_type = str(item.get("type") or "expense").casefold()
            is_income = tx_type == "income"
            is_subscription = _looks_like_subscription(item.get("category"), item.get("name"))
            if is_income:
                kind = "expected_income"
                kind_label = "Expected income"
                tone = "income"
                priority = 10
            elif is_subscription:
                kind = "subscription"
                kind_label = "Subscription"
                tone = "subscription"
                priority = 30
            else:
                kind = "recurring_expense"
                kind_label = "Recurring expense"
                tone = "expense"
                priority = 35
            _add_event(
                events,
                due,
                title=str(item.get("name") or kind_label),
                amount=float(item.get("amount_value", 0.0) or 0.0),
                direction="in" if is_income else "out",
                kind=kind,
                kind_label=kind_label,
                tone=tone,
                source="Recurring",
                endpoint="pending.recurring_page",
                detail=f"{item.get('category', '')} · {item.get('account_label', '')} · {item.get('status_label', 'Forecast')}",
                sort_priority=priority,
            )
    except Exception:
        pass

    # Pending queue: visible near-term payments already generated.
    try:
        pending_rows = pending_rows_for_scope(load_pending(), selected_scope)
        for row in pending_rows:
            if str(row.get("status") or "pending").casefold() != "pending":
                continue
            due = _parse_date(row.get("date_due"))
            if not _inside(due, window_start, window_end):
                continue
            tx_type = str(row.get("type") or "expense").casefold()
            is_income = tx_type == "income"
            kind = "pending_recurring" if row.get("source") == "recurring" else "pending_payment"
            _add_event(
                events,
                due,
                title=str(row.get("description") or row.get("category") or "Pending payment"),
                amount=_amount(row.get("amount")),
                direction="in" if is_income else "out",
                kind=kind,
                kind_label="Pending recurring" if kind == "pending_recurring" else "Pending payment",
                tone="income" if is_income else "pending",
                source="Pending",
                endpoint="pending.pending_page",
                detail=f"{row.get('category', '')} · {row.get('account_name_snapshot') or row.get('account_label') or row.get('account', '')}",
                sort_priority=5,
            )
    except Exception:
        pass

    # Debts and debt rules.
    try:
        debts = debts_for_scope(selected_scope)
        active_debts = {
            str(row.get("id", "")): row
            for row in debts
            if str(row.get("status") or "active").casefold() == "active" and _amount(row.get("remaining_amount")) > 0
        }
        for row in active_debts.values():
            due = _parse_date(row.get("due_date"))
            if not _inside(due, window_start, window_end):
                continue
            _add_event(
                events,
                due,
                title=str(row.get("name") or "Debt due"),
                amount=_amount(row.get("remaining_amount")),
                direction="out",
                kind="debt_due",
                kind_label="Debt due",
                tone="debt",
                source="Debt",
                endpoint="debts.debts_page",
                detail=f"{row.get('creditor', 'Unknown creditor')} · remaining",
                sort_priority=15,
            )
        for rule in load_debt_rules():
            if str(rule.get("active", "1")).strip().casefold() not in {"1", "true", "yes", "on"}:
                continue
            debt = active_debts.get(str(rule.get("debt_id", "")))
            if not debt:
                continue
            due = next_due_date_for_rule(rule, today=window_start)
            if not _inside(due, window_start, window_end):
                continue
            raw_amount = _amount(rule.get("amount")) or _amount(debt.get("remaining_amount"))
            _add_event(
                events,
                due,
                title=str(rule.get("name") or debt.get("name") or "Debt payment"),
                amount=min(raw_amount, _amount(debt.get("remaining_amount"))),
                direction="out",
                kind="debt_payment",
                kind_label="Debt payment",
                tone="debt",
                source="Debt rule",
                endpoint="debts.debts_page",
                detail=f"{debt.get('creditor', 'Unknown creditor')} · scheduled",
                sort_priority=18,
            )
    except Exception:
        pass

    # Payables.
    try:
        from money_manager.repositories.payables import load_payables

        for row in payable_rows_for_scope(load_payables(), selected_scope):
            if str(row.get("status") or "active").casefold() != "active" or _amount(row.get("remaining_amount")) <= 0:
                continue
            due = _parse_date(row.get("due_date"))
            if not _inside(due, window_start, window_end):
                continue
            _add_event(
                events,
                due,
                title=str(row.get("name") or "Payable"),
                amount=_amount(row.get("remaining_amount")),
                direction="out",
                kind="payable",
                kind_label="Payable",
                tone="payable",
                source="Payable",
                endpoint="payables.payables_page",
                detail=f"{row.get('payee', 'Unknown payee')} · {row.get('category', '')}",
                sort_priority=20,
            )
    except Exception:
        pass

    # Receivables.
    try:
        for row in receivables_for_scope(selected_scope):
            if str(row.get("status") or "active").casefold() != "active" or _amount(row.get("remaining_amount")) <= 0:
                continue
            due = _parse_date(row.get("due_date"))
            if not _inside(due, window_start, window_end):
                continue
            _add_event(
                events,
                due,
                title=str(row.get("name") or "Receivable"),
                amount=_amount(row.get("remaining_amount")),
                direction="in",
                kind="receivable",
                kind_label="Receivable",
                tone="income",
                source="Receivable",
                endpoint="receivables.receivables_page",
                detail=f"{row.get('debtor', 'Unknown debtor')} · expected collection",
                sort_priority=12,
            )
    except Exception:
        pass

    # Standalone planned expenses.
    try:
        for row in active_planned_expenses_for_forecast():
            if not _row_matches_scope(row, selected_scope):
                continue
            due = _parse_date(row.get("due_date"))
            if not _inside(due, window_start, window_end):
                continue
            _add_event(
                events,
                due,
                title=str(row.get("title") or "Planned expense"),
                amount=_amount(row.get("remaining_amount") or row.get("expected_amount")),
                direction="out",
                kind="planned_expense",
                kind_label="Planned expense",
                tone="planned",
                source="Planned expenses",
                endpoint="planned_expenses.planned_expenses_page",
                detail=f"{row.get('vendor', '') or row.get('category', '')} · one-time plan",
                sort_priority=24,
            )
    except Exception:
        pass

    # One-time planned expenses from projects.
    try:
        for row in load_planned_items():
            if str(row.get("status") or "active").casefold() != "active" or _amount(row.get("remaining_amount")) <= 0:
                continue
            if str(row.get("payable_id") or "").strip():
                # The linked payable already appears in the calendar.
                continue
            due = _parse_date(row.get("due_date"))
            if not _inside(due, window_start, window_end):
                continue
            _add_event(
                events,
                due,
                title=str(row.get("name") or "Planned expense"),
                amount=_amount(row.get("remaining_amount")),
                direction="out",
                kind="planned_expense",
                kind_label="Planned expense",
                tone="planned",
                source="Project plan",
                endpoint="expense_projects.expense_projects_page",
                detail=f"{row.get('vendor', '') or row.get('category', '')} · one-time plan",
                sort_priority=25,
            )
    except Exception:
        pass

    return _dedupe_events(events)


def _add_event(
    events: list[dict[str, Any]],
    due: date | None,
    *,
    title: str,
    amount: float,
    direction: str,
    kind: str,
    kind_label: str,
    tone: str,
    source: str,
    endpoint: str,
    detail: str,
    sort_priority: int,
) -> None:
    if due is None:
        return
    title = " ".join(str(title or kind_label).split()).strip() or kind_label
    amount = max(0.0, float(amount or 0.0))
    events.append({
        "id": f"{kind}:{due.isoformat()}:{title}:{amount:.2f}",
        "date": due.isoformat(),
        "day": due.day,
        "title": title,
        "amount": amount,
        "amount_label": f"€ {amount:.2f}",
        "direction": "in" if direction == "in" else "out",
        "kind": kind,
        "kind_label": kind_label,
        "tone": tone,
        "source": source,
        "href_endpoint": endpoint,
        "href_label": "Open",
        "detail": " · ".join(part for part in str(detail or "").split(" · ") if part),
        "sort_priority": sort_priority,
    })


def _dedupe_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str, str]] = set()
    out: list[dict[str, Any]] = []
    for event in events:
        key = (event.get("date", ""), event.get("kind", ""), event.get("title", ""), event.get("amount_label", ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(event)
    return out


def _parse_month(value: str | None, today: date) -> date:
    raw = str(value or "").strip()
    if raw:
        try:
            parsed = datetime.strptime(raw[:7], "%Y-%m").date()
            return date(parsed.year, parsed.month, 1)
        except ValueError:
            pass
    return date(today.year, today.month, 1)


def _add_months(value: date, months: int) -> date:
    month = value.month - 1 + months
    year = value.year + month // 12
    month = month % 12 + 1
    return date(year, month, 1)


def _parse_date(value: object) -> date | None:
    parsed = parse_date(value)
    if parsed:
        return parsed
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw).date()
    except ValueError:
        return None


def _inside(value: date | None, start: date, end: date) -> bool:
    return value is not None and start <= value <= end


def _amount(value: object) -> float:
    try:
        return max(0.0, float(str(value or 0).replace(",", ".")))
    except (TypeError, ValueError):
        return 0.0


def _looks_like_subscription(*parts: object) -> bool:
    text = " ".join(str(part or "") for part in parts).casefold()
    keywords = ["subscription", "subscriptions", "abbon", "onedrive", "netflix", "spotify", "icloud", "google", "adobe", "canva", "prime", "storage"]
    return any(keyword in text for keyword in keywords)


def _row_matches_scope(row: Mapping[str, Any], scope: Mapping[str, Any] | str | None) -> bool:
    if not _scope_is_limited(scope):
        return True
    account_id = str(row.get("account_id") or row.get("account") or "").strip()
    if not account_id:
        return True
    if isinstance(scope, Mapping):
        allowed = {str(value) for value in scope.get("included_account_ids") or [] if value}
        selected = str(scope.get("account_id") or "").strip()
        if selected:
            allowed.add(selected)
        return account_id in allowed if allowed else True
    return account_id == str(scope).strip()


def _scope_is_limited(scope: Mapping[str, Any] | str | None) -> bool:
    if isinstance(scope, Mapping):
        return bool(scope.get("is_account") or scope.get("account_id") or scope.get("scope") not in {None, "", "global"})
    return bool(scope and str(scope) != "global")
