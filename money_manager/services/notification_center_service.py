from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Mapping

from money_manager.repositories.pending import load_pending
from money_manager.repositories.recurring import normalize_amount, parse_date
from money_manager.services.account_scope_service import (
    debts_for_scope,
    payable_rows_for_scope,
    pending_rows_for_scope,
    receivables_for_scope,
    recurring_rows_for_scope,
    scope_balance_summary,
)
from money_manager.services.notification_service import build_notification_context_cached
from money_manager.services.payable_service import immediate_payable_reminders
from money_manager.services.recurring_service import recurring_forecast_for_period
from money_manager.services.transaction_service import load_transactions


def build_notification_center_context(
    *,
    selected_scope: Mapping[str, Any] | str | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    categories = [
        _current_alerts(today),
        _upcoming_payables(selected_scope, today),
        _upcoming_debts(selected_scope, today),
        _pending_recurring(selected_scope, today),
        _expected_incomes(selected_scope, today),
        _subscriptions(today, selected_scope),
        _low_balance(selected_scope),
        _debts_almost_paid(selected_scope),
        _large_expenses(selected_scope, today),
        _forgotten_unpaid(selected_scope, today),
    ]

    all_items = [item for category in categories for item in category["items"]]
    unread_items = [item for item in all_items if item.get("is_unread", True)]
    critical_count = sum(1 for item in all_items if item.get("tone") == "critical")
    warning_count = sum(1 for item in all_items if item.get("tone") == "warning")

    return {
        "notification_center_categories": categories,
        "notification_center_items": all_items,
        "notification_center_summary": {
            "total": len(all_items),
            "unread": len(unread_items),
            "critical": critical_count,
            "warning": warning_count,
            "sections": len(categories),
        },
        "notification_center_today": today.isoformat(),
    }


def _current_alerts(today: date) -> dict[str, Any]:
    context = build_notification_context_cached(today=today)
    items = []
    for item in context.get("items", []):
        items.append(_item(
            raw_id=str(item.get("id") or "alert"),
            tone=str(item.get("tone") or "info"),
            label=str(item.get("label") or "Alert"),
            title=str(item.get("title") or "Notification"),
            amount_label=str(item.get("summary") or ""),
            date_label=str(item.get("sort_date") or ""),
            meta=str(item.get("meta") or ""),
            detail=str(item.get("detail") or ""),
            icon=str(item.get("icon") or "•"),
            href_endpoint=str(item.get("href_endpoint") or "dashboard.index"),
            href_label=str(item.get("href_label") or "Open"),
            actions=_alert_actions(item),
            is_unread=bool(item.get("is_unread", True)),
        ))
    return _category(
        key="current_alerts",
        eyebrow="Alerts",
        title="Notifications to read",
        description="Urgent and recent reminders generated from pending payments, debts, payables and recurring rules.",
        empty="No active alerts right now.",
        items=items,
    )


def _upcoming_payables(scope, today: date) -> dict[str, Any]:
    items = []
    try:
        reminders = immediate_payable_reminders(limit=12, today=today, scope=scope)
    except Exception:
        reminders = []
    for row in reminders:
        items.append(_item(
            raw_id=f"payable:{row.get('id')}",
            tone=_tone_from_due(row.get("due_date"), today, default=str(row.get("tone") or "info")),
            label=str(row.get("due_label") or "Payable"),
            title=str(row.get("name") or "Payable"),
            amount_label=_money(row.get("remaining_amount")),
            date_label=str(row.get("due_date") or "No due date"),
            meta=f"{row.get('payee', 'Unknown payee')} · {row.get('category', 'Payable')} · {row.get('account_label', '')}",
            detail=str(row.get("description") or "Open payable reminder. It is shown even if it is not urgent enough to become an alert."),
            icon="⇣",
            href_endpoint="payables.payables_page",
            href_label="Open payable",
            actions=["pay_now", "snooze", "ignore", "reminder_date"],
        ))
    return _category(
        key="upcoming_payables",
        eyebrow="Payables",
        title="Upcoming payables",
        description="Active payables ordered by closest due date, including rows without urgent alerts.",
        empty="No active payable reminders.",
        items=items,
    )


def _upcoming_debts(scope, today: date) -> dict[str, Any]:
    rows = []
    try:
        rows = debts_for_scope(scope)
    except Exception:
        rows = []
    prepared = []
    for row in rows:
        if str(row.get("status") or "active").casefold() != "active":
            continue
        remaining = _amount(row.get("remaining_amount"))
        if remaining <= 0:
            continue
        due = _date(row.get("due_date")) or _date(row.get("start_date")) or _datetime_date(row.get("created_at")) or date.max
        prepared.append((due, row, remaining))
    prepared.sort(key=lambda item: (item[0], str(item[1].get("name") or "").casefold()))
    items = []
    for due, row, remaining in prepared[:12]:
        due_date = _date(row.get("due_date"))
        items.append(_item(
            raw_id=f"debt:{row.get('id')}",
            tone=_tone_from_due(due_date, today, default="info"),
            label=_due_label(due_date, today, fallback="No due date"),
            title=str(row.get("name") or "Debt"),
            amount_label=_money(remaining),
            date_label=due_date.isoformat() if due_date else "No due date",
            meta=f"{row.get('creditor', 'Unknown creditor')} · active debt",
            detail="Open debt reminder. Pay it, move it to Pocket, or update the remaining amount.",
            icon="−",
            href_endpoint="debts.debts_page",
            href_label="Open debt",
            actions=["pay_now", "snooze", "ignore", "reminder_date"],
        ))
    return _category(
        key="upcoming_debts",
        eyebrow="Debts",
        title="Upcoming debts",
        description="Active debts with due dates first, then older active debts without a due date.",
        empty="No active debt reminders.",
        items=items,
    )


def _pending_recurring(scope, today: date) -> dict[str, Any]:
    try:
        rows = pending_rows_for_scope(load_pending(), scope)
    except Exception:
        rows = []
    prepared = []
    for row in rows:
        if str(row.get("status") or "pending").casefold() != "pending":
            continue
        if row.get("source") != "recurring":
            continue
        due = _date(row.get("date_due")) or date.max
        prepared.append((due, row))
    prepared.sort(key=lambda item: (item[0], str(item[1].get("description") or "").casefold()))
    items = []
    for due, row in prepared[:12]:
        is_income = str(row.get("type") or "expense").casefold() == "income"
        items.append(_item(
            raw_id=f"pending-recurring:{row.get('id')}",
            tone="income" if is_income else _tone_from_due(due if due != date.max else None, today, default="warning"),
            label=_due_label(due if due != date.max else None, today, fallback="Pending recurring"),
            title=str(row.get("description") or row.get("category") or "Recurring payment"),
            amount_label=_money(row.get("amount")),
            date_label=due.isoformat() if due != date.max else "No due date",
            meta=f"{row.get('category', '')} · {row.get('account_name_snapshot') or row.get('account_label') or row.get('account', '')}",
            detail="This recurring rule has already generated a pending row. Execute, delay or discard it from Pending.",
            icon="↻",
            href_endpoint="pending.pending_page",
            href_label="Open pending",
            actions=["pay_now", "snooze", "ignore", "reminder_date"],
        ))
    return _category(
        key="pending_recurring",
        eyebrow="Recurring",
        title="Pending recurring payments",
        description="Recurring payments that are already waiting in the Pending queue.",
        empty="No pending recurring payments.",
        items=items,
    )


def _expected_incomes(scope, today: date) -> dict[str, Any]:
    start = date(today.year, today.month, 1)
    if today.month == 12:
        end = date(today.year + 1, 1, 31)
    else:
        next_month = date(today.year, today.month + 1, 1)
        if next_month.month == 12:
            end = date(next_month.year, next_month.month, 31)
        else:
            end = date(next_month.year, next_month.month, (date(next_month.year, next_month.month + 1, 1) - timedelta(days=1)).day)
    items = []
    try:
        from money_manager.repositories.recurring import load_recurring

        scoped_rules = recurring_rows_for_scope(load_recurring(), scope)
        scoped_ids = {str(row.get("id", "")) for row in scoped_rules}
        scope_limited = _scope_is_limited(scope)
        forecast = recurring_forecast_for_period(start, end, today=today)
        for row in forecast.get("items", []):
            if str(row.get("type") or "").casefold() != "income":
                continue
            if scope_limited and str(row.get("rule_id", "")) not in scoped_ids:
                continue
            due = _date(row.get("payment_due_date"))
            items.append(_item(
                raw_id=f"expected-income:{row.get('rule_id')}:{row.get('payment_due_date')}",
                tone="income",
                label=_due_label(due, today, fallback="Expected income"),
                title=str(row.get("name") or "Expected income"),
                amount_label=str(row.get("amount_str") or _money(row.get("amount_value"))),
                date_label=row.get("payment_due_date") or "",
                meta=f"{row.get('category', '')} · {row.get('account_label', '')} · {row.get('status_label', 'Forecast')}",
                detail="Expected income from recurring rules for the current and next month.",
                icon="+",
                href_endpoint="pending.recurring_page",
                href_label="Open rule",
                actions=["open", "snooze", "ignore", "reminder_date"],
            ))
    except Exception:
        pass
    return _category(
        key="expected_incomes",
        eyebrow="Income",
        title="Expected incomes",
        description="Salaries, cedolini and recurring income rules expected soon.",
        empty="No expected recurring income in this window.",
        items=items[:10],
    )


def _subscriptions(today: date, scope) -> dict[str, Any]:
    start = date(today.year, today.month, 1)
    end = _add_months(start, 2) - timedelta(days=1)
    items = []
    try:
        from money_manager.repositories.recurring import load_recurring

        scoped_rules = recurring_rows_for_scope(load_recurring(), scope)
        scoped_ids = {str(row.get("id", "")) for row in scoped_rules}
        scope_limited = _scope_is_limited(scope)
        forecast = recurring_forecast_for_period(start, end, today=today)
        fallback = []
        for row in forecast.get("items", []):
            if str(row.get("type") or "expense").casefold() == "income":
                continue
            if scope_limited and str(row.get("rule_id", "")) not in scoped_ids:
                continue
            if _looks_like_subscription(row.get("category"), row.get("name")):
                target = items
            else:
                target = fallback
            due = _date(row.get("payment_due_date"))
            target.append(_item(
                raw_id=f"subscription:{row.get('rule_id')}:{row.get('payment_due_date')}",
                tone=_tone_from_due(due, today, default="info"),
                label=_due_label(due, today, fallback="Renewing soon"),
                title=str(row.get("name") or "Subscription"),
                amount_label=str(row.get("amount_str") or _money(row.get("amount_value"))),
                date_label=row.get("payment_due_date") or "",
                meta=f"{row.get('category', '')} · {row.get('account_label', '')} · {row.get('status_label', 'Forecast')}",
                detail="Recurring expense renewal. Review whether it should still be active.",
                icon="↻",
                href_endpoint="pending.recurring_page",
                href_label="Open recurring",
                actions=["open", "snooze", "ignore", "reminder_date"],
            ))
        if not items:
            items = fallback[:8]
    except Exception:
        pass
    return _category(
        key="subscriptions",
        eyebrow="Subscriptions",
        title="Subscriptions renewing soon",
        description="Recurring subscriptions and recurring expenses due in the next two months.",
        empty="No subscription-like recurring expenses found soon.",
        items=items[:10],
    )


def _low_balance(scope) -> dict[str, Any]:
    items = []
    try:
        summary = scope_balance_summary(scope)
        net = float(summary.get("net_balance", 0.0) or 0.0)
        pending = float(summary.get("pending_total", 0.0) or 0.0)
        projected = float(summary.get("net_after_pending", net - pending) or (net - pending))
        if projected < 0:
            tone = "critical"
            label = "Negative after pending"
            detail = "Your projected balance goes below zero after open pending payments."
        elif projected < 150:
            tone = "warning"
            label = "Low projected buffer"
            detail = "Your projected balance after pending payments is under €150."
        else:
            tone = "good"
            label = "Balance OK"
            detail = "No low-balance warning for the selected scope."
        if tone != "good":
            items.append(_item(
                raw_id=f"low-balance:{projected:.2f}",
                tone=tone,
                label=label,
                title="Low balance warning",
                amount_label=_money(projected),
                date_label="Projected after pending",
                meta=f"Current net {_money(net)} · pending {_money(pending)}",
                detail=detail,
                icon="!",
                href_endpoint="dashboard.index",
                href_label="Open dashboard",
                actions=["open", "snooze", "ignore", "reminder_date"],
            ))
    except Exception:
        pass
    return _category(
        key="low_balance",
        eyebrow="Balance",
        title="Low balance warning",
        description="Projected cash pressure after pending movements.",
        empty="No low-balance warning for the selected scope.",
        items=items,
    )


def _debts_almost_paid(scope) -> dict[str, Any]:
    rows = []
    try:
        rows = debts_for_scope(scope)
    except Exception:
        rows = []
    items = []
    for row in rows:
        if str(row.get("status") or "active").casefold() != "active":
            continue
        original = _amount(row.get("original_amount"))
        remaining = _amount(row.get("remaining_amount"))
        if original <= 0 or remaining <= 0:
            continue
        progress = 100.0 * max(0.0, original - remaining) / original
        if remaining <= 25 or progress >= 90:
            items.append(_item(
                raw_id=f"debt-almost-paid:{row.get('id')}",
                tone="good",
                label=f"{progress:.0f}% paid",
                title=str(row.get("name") or "Debt almost paid"),
                amount_label=f"{_money(remaining)} left",
                date_label=row.get("due_date") or "No due date",
                meta=f"{row.get('creditor', 'Unknown creditor')} · original {_money(original)}",
                detail="This debt is close to being fully paid. Consider closing it now if the remaining amount is small.",
                icon="✓",
                href_endpoint="debts.debts_page",
                href_label="Open debts",
                actions=["pay_now", "snooze", "ignore"],
            ))
    return _category(
        key="debts_almost_paid",
        eyebrow="Debts",
        title="Debts almost paid",
        description="Active debts that are above 90% progress or have a very small remaining balance.",
        empty="No debts are almost closed.",
        items=items[:10],
    )


def _large_expenses(scope, today: date) -> dict[str, Any]:
    items = []
    try:
        df = load_transactions()
        if df is None or df.empty:
            raise ValueError("empty")
        # Scope filtering is intentionally light here; transaction scope helpers
        # are route-oriented and the center should never break because of data drift.
        month_start = date(today.year, today.month, 1).isoformat()
        df = df.copy()
        df["_date"] = df.get("date", "").astype(str).str[:10]
        if "type" in df.columns:
            df = df[df["type"].astype(str).str.casefold() == "expense"]
        df = df[df["_date"] >= month_start]
        if "amount" in df.columns:
            df["_amount"] = df["amount"].apply(_amount)
        else:
            df["_amount"] = 0.0
        threshold = max(100.0, float(df["_amount"].quantile(0.90) if not df.empty else 100.0))
        df = df[df["_amount"] >= threshold].sort_values("_amount", ascending=False).head(8)
        for _, row in df.iterrows():
            title = str(row.get("description") or row.get("sub_category") or row.get("category") or "Large expense")
            items.append(_item(
                raw_id=f"large-expense:{row.get('id', '')}:{row.get('_date', '')}:{row.get('_amount', 0):.2f}",
                tone="warning",
                label="Large expense",
                title=title,
                amount_label=_money(row.get("_amount")),
                date_label=str(row.get("_date") or ""),
                meta=f"{row.get('category', '')} · {row.get('account_name_snapshot') or row.get('account', '')}",
                detail="This is one of the largest expenses in the current month. Review it if it looks unusual.",
                icon="€",
                href_endpoint="transactions.transactions_page",
                href_label="Open transactions",
                actions=["open", "snooze", "ignore", "convert_payable", "convert_debt"],
            ))
    except Exception:
        pass
    return _category(
        key="large_expenses",
        eyebrow="Spending",
        title="Large expenses detected",
        description="Largest current-month expense rows that may deserve a quick review.",
        empty="No unusually large current-month expenses detected.",
        items=items,
    )


def _forgotten_unpaid(scope, today: date) -> dict[str, Any]:
    items = []
    stale_before = today - timedelta(days=30)
    try:
        from money_manager.repositories.payables import load_payables

        for row in payable_rows_for_scope(load_payables(), scope):
            if str(row.get("status") or "active").casefold() != "active" or _amount(row.get("remaining_amount")) <= 0:
                continue
            anchor = _date(row.get("due_date")) or _date(row.get("start_date")) or _datetime_date(row.get("created_at"))
            if not anchor or anchor > stale_before:
                continue
            items.append(_item(
                raw_id=f"forgotten-payable:{row.get('id')}",
                tone="info",
                label=f"Open {max(0, (today - anchor).days)} days",
                title=str(row.get("name") or "Forgotten payable"),
                amount_label=_money(row.get("remaining_amount")),
                date_label=anchor.isoformat(),
                meta=f"{row.get('payee', 'Unknown payee')} · payable",
                detail="This payable has been open for a while. Pay, delay, cancel or archive it.",
                icon="◇",
                href_endpoint="payables.payables_page",
                href_label="Open payables",
                actions=["pay_now", "snooze", "ignore", "reminder_date"],
            ))
    except Exception:
        pass
    try:
        for row in debts_for_scope(scope):
            if str(row.get("status") or "active").casefold() != "active" or _amount(row.get("remaining_amount")) <= 0:
                continue
            anchor = _date(row.get("due_date")) or _date(row.get("start_date")) or _datetime_date(row.get("created_at"))
            if not anchor or anchor > stale_before:
                continue
            items.append(_item(
                raw_id=f"forgotten-debt:{row.get('id')}",
                tone="info",
                label=f"Open {max(0, (today - anchor).days)} days",
                title=str(row.get("name") or "Forgotten debt"),
                amount_label=_money(row.get("remaining_amount")),
                date_label=anchor.isoformat(),
                meta=f"{row.get('creditor', 'Unknown creditor')} · debt",
                detail="This debt has been open for a while. Pay, pocket, cancel or update it.",
                icon="?",
                href_endpoint="debts.debts_page",
                href_label="Open debts",
                actions=["pay_now", "snooze", "ignore", "reminder_date"],
            ))
    except Exception:
        pass
    items.sort(key=lambda row: (row.get("date_label", "9999-99-99"), row.get("title", "")))
    return _category(
        key="forgotten_unpaid",
        eyebrow="Review",
        title="Forgotten / unpaid items",
        description="Older open debts and payables that may have been forgotten.",
        empty="No stale unpaid item found.",
        items=items[:12],
    )


def _category(*, key: str, eyebrow: str, title: str, description: str, empty: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "key": key,
        "eyebrow": eyebrow,
        "title": title,
        "description": description,
        "empty": empty,
        "items": items,
        "count": len(items),
    }


def _item(
    *,
    raw_id: str,
    tone: str,
    label: str,
    title: str,
    amount_label: str,
    date_label: str,
    meta: str,
    detail: str,
    icon: str,
    href_endpoint: str,
    href_label: str,
    actions: list[str],
    is_unread: bool = True,
) -> dict[str, Any]:
    return {
        "id": raw_id,
        "tone": tone if tone in {"critical", "warning", "info", "good", "income"} else "info",
        "label": label,
        "title": title,
        "amount_label": amount_label,
        "date_label": date_label,
        "meta": meta,
        "detail": detail,
        "icon": icon,
        "href_endpoint": href_endpoint,
        "href_label": href_label,
        "actions": actions,
        "is_unread": is_unread,
    }


def _alert_actions(item: Mapping[str, Any]) -> list[str]:
    endpoint = str(item.get("href_endpoint") or "")
    actions = ["open", "snooze", "ignore", "reminder_date"]
    if "payables" in endpoint or "debts" in endpoint or "pending" in endpoint:
        actions.insert(0, "pay_now")
    return actions


def _due_label(value: date | None, today: date, *, fallback: str) -> str:
    if value is None:
        return fallback
    delta = (value - today).days
    if delta < 0:
        return f"Overdue by {abs(delta)} day{'s' if abs(delta) != 1 else ''}"
    if delta == 0:
        return "Due today"
    if delta == 1:
        return "Due tomorrow"
    return f"Due in {delta} days"


def _tone_from_due(value: date | str | None, today: date, *, default: str) -> str:
    parsed = _date(value)
    if parsed is None:
        return default
    if parsed <= today:
        return "critical"
    if parsed <= today + timedelta(days=7):
        return "warning"
    return default


def _date(value: object) -> date | None:
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


def _datetime_date(value: object) -> date | None:
    return _date(value)


def _amount(value: object) -> float:
    try:
        return max(0.0, float(str(value or 0).replace(",", ".")))
    except (TypeError, ValueError):
        return 0.0


def _money(value: object) -> str:
    return f"€ {_amount(value):.2f}"


def _add_months(value: date, months: int) -> date:
    month = value.month - 1 + months
    year = value.year + month // 12
    month = month % 12 + 1
    return date(year, month, 1)


def _looks_like_subscription(*parts: object) -> bool:
    text = " ".join(str(part or "") for part in parts).casefold()
    keywords = ["subscription", "subscriptions", "abbon", "onedrive", "netflix", "spotify", "icloud", "google", "adobe", "canva", "prime", "storage"]
    return any(keyword in text for keyword in keywords)


def _scope_is_limited(scope: Mapping[str, Any] | str | None) -> bool:
    if isinstance(scope, Mapping):
        return bool(scope.get("is_account") or scope.get("account_id") or scope.get("scope") not in {None, "", "global"})
    return bool(scope and str(scope) != "global")
