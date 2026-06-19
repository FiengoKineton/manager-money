from __future__ import annotations

from datetime import date, datetime, timedelta
from hashlib import sha1
from typing import Any

from money_manager.repositories.debts import load_debts
from money_manager.repositories.payables import load_payables
from money_manager.repositories.pending import load_pending
from money_manager.repositories.recurring import load_recurring, normalize_amount, parse_date
from money_manager.services.debt_service import next_due_date_for_rule as next_debt_rule_due_date
from money_manager.services.recurring_service import is_rule_finished, next_due_date_for_rule as next_recurring_due_date


MAX_CURRENT_NOTIFICATIONS = 14
UPCOMING_DAYS = 3
DEBT_STALE_DAYS = 45
PAYABLE_STALE_DAYS = 21


def attach_notification_state(context: dict[str, Any]) -> dict[str, Any]:
    try:
        from copy import deepcopy
        from money_manager.services.notification_state_service import (
            notification_history,
            read_notification_ids,
        )

        output = deepcopy(context)
        items = output.get("items", [])
        if not isinstance(items, list):
            items = []
            output["items"] = items

        read_ids = read_notification_ids()

        unread_count = 0
        unread_urgent_count = 0
        current_ids = set()

        for item in items:
            item_id = str(item.get("id", ""))
            current_ids.add(item_id)

            is_read = item_id in read_ids
            item["is_read"] = is_read
            item["is_unread"] = not is_read

            if not is_read:
                unread_count += 1
                if item.get("tone") in {"critical", "warning"}:
                    unread_urgent_count += 1

        history = [
            item
            for item in notification_history(limit=20)
            if str(item.get("id", "")) not in current_ids
        ]

        output["history"] = history
        output["unread_count"] = unread_count
        output["urgent_count"] = unread_urgent_count
        output["has_unread_candidate"] = unread_count > 0

        return output
    except Exception:
        return context

def build_notification_context_cached(today: date | None = None) -> dict[str, Any]:
    today = today or date.today()

    try:
        from money_manager.services.cache_service import cached_calculation

        raw_context = cached_calculation(
            "notifications.context",
            lambda: build_notification_context(today, include_state=False),
            extra_fingerprint={"today": today.isoformat()},
            allow_stale_on_error=True,
        )
    except Exception:
        raw_context = build_notification_context(today, include_state=False)

    return attach_notification_state(raw_context)


def build_notification_context(
    today: date | None = None,
    *,
    include_state: bool = True,
) -> dict[str, Any]:
    """Build topbar reminder notifications without mutating app data.

    This service intentionally reads CSV state only. It does not generate, execute,
    delay, delete, or mark any payment as paid. The panel is a reminder surface;
    the actual action still happens on Pending, Debts, Payables, or Recurring.
    """

    today = today or date.today()
    items: list[dict[str, Any]] = []

    try:
        items.extend(_pending_notifications(today))
        items.extend(_debt_notifications(today))
        items.extend(_payable_notifications(today))
        items.extend(_recurring_notifications(today))
    except Exception:
        # Topbar notifications must never break the app shell.
        items = []

    severity_order = {"critical": 0, "warning": 1, "info": 2, "good": 3}
    items = sorted(
        items,
        key=lambda item: (
            severity_order.get(item.get("tone", "info"), 9),
            item.get("sort_date", date.max),
            item.get("title", ""),
        ),
    )

    # Deduplicate by ID while preserving the sorted priority.
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        item_id = item.get("id") or _stable_id(item.get("title", ""), item.get("detail", ""))
        item["id"] = item_id
        if item_id in seen:
            continue
        seen.add(item_id)
        deduped.append(item)

    current = deduped[:MAX_CURRENT_NOTIFICATIONS]
    urgent_count = sum(1 for item in current if item.get("tone") in {"critical", "warning"})

    for item in current:
        # Jinja/HTML data attributes are easier if dates are strings.
        sort_date = item.get("sort_date")
        item["sort_date"] = sort_date.isoformat() if isinstance(sort_date, date) else str(sort_date or "")
        item["is_urgent"] = item.get("tone") in {"critical", "warning"}

    context = {
        "items": current,
        "count": len(current),
        "urgent_count": urgent_count,
        "has_unread_candidate": urgent_count > 0,
        "history": [],
        "unread_count": urgent_count,
    }

    return attach_notification_state(context) if include_state else context


def _pending_notifications(today: date) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    upcoming_limit = today + timedelta(days=UPCOMING_DAYS)

    for row in load_pending():
        if str(row.get("status", "pending")).lower() != "pending":
            continue

        due = _parse_date(row.get("date_due"))
        if not due or due > upcoming_limit:
            continue

        amount = _amount(row.get("amount"))
        description = _clean(row.get("description")) or _clean(row.get("category")) or "Pending payment"
        direction = "income" if str(row.get("type", "expense")).lower() == "income" else "payment"

        if due < today:
            label = f"Overdue by {(today - due).days} day{'s' if (today - due).days != 1 else ''}"
            tone = "critical"
            title = f"Overdue {direction}: {description}"
        elif due == today:
            label = "Due today"
            tone = "critical"
            title = f"Today: {description}"
        else:
            days = (due - today).days
            label = f"Due in {days} day{'s' if days != 1 else ''}"
            tone = "warning"
            title = f"Upcoming {direction}: {description}"

        out.append(_item(
            raw_id=f"pending:{row.get('id', '')}:{due.isoformat()}:{row.get('status', '')}",
            tone=tone,
            label=label,
            icon="◷",
            title=title,
            summary=f"{_format_amount(amount)} · {due.isoformat()}",
            detail=(
                f"This row is still pending. Open Pending payments to execute it, delay it, "
                f"or edit the due date before it affects your planning."
            ),
            meta=f"Pending · {row.get('category', '') or 'No category'} · {row.get('account', '') or 'No account'}",
            href_endpoint="pending.pending_page",
            href_label="Open pending",
            sort_date=due,
        ))

    return out


def _debt_notifications(today: date) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    upcoming_limit = today + timedelta(days=7)

    for row in load_debts():
        if str(row.get("status", "active")).lower() != "active":
            continue
        remaining = _amount(row.get("remaining_amount"))
        if remaining <= 0.005:
            continue

        name = _clean(row.get("name")) or "Debt"
        creditor = _clean(row.get("creditor")) or "Unknown creditor"
        due = _parse_date(row.get("due_date"))
        age_date = _parse_date(row.get("start_date")) or _parse_datetime_date(row.get("created_at"))

        if due and due <= upcoming_limit:
            if due < today:
                label = f"Debt overdue by {(today - due).days} day{'s' if (today - due).days != 1 else ''}"
                tone = "critical"
            elif due == today:
                label = "Debt due today"
                tone = "critical"
            else:
                label = f"Debt due in {(due - today).days} days"
                tone = "warning"

            out.append(_item(
                raw_id=f"debt-due:{row.get('id', '')}:{due.isoformat()}:{remaining:.2f}",
                tone=tone,
                label=label,
                icon="−",
                title=f"Check debt: {name}",
                summary=f"{_format_amount(remaining)} remaining · {creditor}",
                detail="This debt has a due date close enough to deserve attention. Open Debts I owe to pay, update, or reschedule it.",
                meta=f"Debt · due {due.isoformat()}",
                href_endpoint="debts.debts_page",
                href_label="Open debts",
                sort_date=due,
            ))
            continue

        if age_date:
            age_days = (today - age_date).days
            if age_days >= DEBT_STALE_DAYS:
                out.append(_item(
                    raw_id=f"debt-stale:{row.get('id', '')}:{age_date.isoformat()}:{remaining:.2f}",
                    tone="info",
                    label=f"Open for {age_days} days",
                    icon="?",
                    title=f"Debt still open: {name}",
                    summary=f"{_format_amount(remaining)} remaining · {creditor}",
                    detail="This debt has been active for a while. It may be fine, but it is worth checking whether you should pay part of it, close it, or update the remaining balance.",
                    meta="Debt review",
                    href_endpoint="debts.debts_page",
                    href_label="Review debt",
                    sort_date=age_date,
                ))

    return out[:4]


def _payable_notifications(today: date) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    upcoming_limit = today + timedelta(days=7)

    for row in load_payables():
        if str(row.get("status", "active")).lower() != "active":
            continue
        remaining = _amount(row.get("remaining_amount"))
        if remaining <= 0.005:
            continue

        name = _clean(row.get("name")) or "Payable"
        payee = _clean(row.get("payee")) or "Unknown payee"
        due = _parse_date(row.get("due_date"))
        age_date = _parse_date(row.get("start_date")) or _parse_datetime_date(row.get("created_at"))

        if due and due <= upcoming_limit:
            if due < today:
                label = f"Payable overdue by {(today - due).days} day{'s' if (today - due).days != 1 else ''}"
                tone = "critical"
            elif due == today:
                label = "Payable due today"
                tone = "critical"
            else:
                label = f"Payable due in {(due - today).days} days"
                tone = "warning"

            out.append(_item(
                raw_id=f"payable-due:{row.get('id', '')}:{due.isoformat()}:{remaining:.2f}",
                tone=tone,
                label=label,
                icon="⇣",
                title=f"Check payable: {name}",
                summary=f"{_format_amount(remaining)} remaining · {payee}",
                detail="This payable is close to its due date. Open Payables to pay it, edit it, or confirm it should stay open.",
                meta=f"Payable · due {due.isoformat()}",
                href_endpoint="payables.payables_page",
                href_label="Open payables",
                sort_date=due,
            ))
            continue

        if age_date:
            age_days = (today - age_date).days
            if age_days >= PAYABLE_STALE_DAYS:
                out.append(_item(
                    raw_id=f"payable-stale:{row.get('id', '')}:{age_date.isoformat()}:{remaining:.2f}",
                    tone="info",
                    label=f"Created {age_days} days ago",
                    icon="◇",
                    title=f"Payable still open: {name}",
                    summary=f"{_format_amount(remaining)} remaining · {payee}",
                    detail="This payable has been open for a while. Check whether it should be paid now, delayed, linked to a project, or closed.",
                    meta="Payable review",
                    href_endpoint="payables.payables_page",
                    href_label="Review payable",
                    sort_date=age_date,
                ))

    return out[:4]


def _recurring_notifications(today: date) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    upcoming_limit = today + timedelta(days=UPCOMING_DAYS)
    pending_sources = {
        (str(row.get("source", "")), str(row.get("source_id", "")))
        for row in load_pending()
        if str(row.get("status", "pending")).lower() == "pending"
    }

    for row in load_recurring():
        if is_rule_finished(row, today=today):
            continue

        rule_id = str(row.get("id", ""))
        # If the rule already has an open pending row, the pending reminder is clearer.
        if ("recurring", rule_id) in pending_sources:
            continue

        due = next_recurring_due_date(row, today=today)
        if not due or due > upcoming_limit:
            continue

        amount = normalize_amount(row.get("amount", 0))
        name = _clean(row.get("name")) or "Recurring rule"
        if due < today:
            label = f"Recurring overdue by {(today - due).days} day{'s' if (today - due).days != 1 else ''}"
            tone = "critical"
        elif due == today:
            label = "Recurring due today"
            tone = "warning"
        else:
            label = f"Recurring in {(due - today).days} days"
            tone = "info"

        out.append(_item(
            raw_id=f"recurring:{rule_id}:{due.isoformat()}:{amount:.2f}",
            tone=tone,
            label=label,
            icon="↻",
            title=f"Recurring check: {name}",
            summary=f"{_format_amount(amount)} · {due.isoformat()}",
            detail="This recurring rule is scheduled soon but does not yet have a visible pending row. Check the rule if you expected it to be queued already.",
            meta=f"Recurring · every {row.get('frequency', '1')} month(s)",
            href_endpoint="pending.recurring_page",
            href_label="Open recurring",
            sort_date=due,
        ))

    # Add debt rule reminders only when they have no open pending row.
    try:
        from money_manager.repositories.debts import load_debt_rules

        pending_debt_sources = {
            str(row.get("source_id", ""))
            for row in load_pending()
            if row.get("source") == "debt" and str(row.get("status", "pending")).lower() == "pending"
        }
        for row in load_debt_rules():
            if str(row.get("active", "1")).strip().lower() not in {"1", "true", "yes", "on"}:
                continue
            debt_id = str(row.get("debt_id", ""))
            if debt_id in pending_debt_sources:
                continue
            due = next_debt_rule_due_date(row, today=today)
            if not due or due > upcoming_limit:
                continue
            out.append(_item(
                raw_id=f"debt-rule:{row.get('id', '')}:{due.isoformat()}",
                tone="warning" if due <= today else "info",
                label="Debt rule due" if due <= today else f"Debt rule in {(due - today).days} days",
                icon="−",
                title=f"Debt schedule check: {_clean(row.get('name')) or 'Debt rule'}",
                summary=due.isoformat(),
                detail="A debt payment rule is scheduled soon. Open Debts I owe to generate, pay, or adjust the debt plan.",
                meta="Debt rule",
                href_endpoint="debts.debts_page",
                href_label="Open debts",
                sort_date=due,
            ))
    except Exception:
        pass

    return out[:4]


def _item(
    *,
    raw_id: str,
    tone: str,
    label: str,
    icon: str,
    title: str,
    summary: str,
    detail: str,
    meta: str,
    href_endpoint: str,
    href_label: str,
    sort_date: date,
) -> dict[str, Any]:
    return {
        "id": _stable_id(raw_id),
        "tone": tone,
        "label": label,
        "icon": icon,
        "title": title,
        "summary": summary,
        "detail": detail,
        "meta": meta,
        "href_endpoint": href_endpoint,
        "href_label": href_label,
        "sort_date": sort_date,
    }


def _stable_id(*parts: object) -> str:
    payload = "|".join(str(part) for part in parts)
    return "mmn-" + sha1(payload.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _amount(value: object) -> float:
    try:
        return max(0.0, float(str(value or 0).replace(",", ".")))
    except (TypeError, ValueError):
        return 0.0


def _format_amount(value: float) -> str:
    return f"€ {value:.2f}"


def _parse_date(value: object) -> date | None:
    return parse_date(value)


def _parse_datetime_date(value: object) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return _parse_date(text[:10])


def _clean(value: object) -> str:
    return " ".join(str(value or "").split()).strip()
