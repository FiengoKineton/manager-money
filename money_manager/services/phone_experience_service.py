from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from money_manager.security.secure_storage import read_csv_secure
from money_manager.config.paths import (
    DEBTS_CSV,
    PAYABLES_CSV,
    PENDING_CSV,
    RECURRING_CSV,
    TRANSACTION_FILES,
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    try:
        if not path.exists():
            return []
        return read_csv_secure(path, [])
    except Exception:
        return []


def _parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


def _parse_amount(value: Any) -> float:
    text = str(value or "0").strip().replace("€", "").replace(" ", "")
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return 0.0


def _transaction_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for tx_type, path in TRANSACTION_FILES.items():
        for row in _read_csv(path):
            tx_date = _parse_date(row.get("date"))
            amount = _parse_amount(row.get("amount"))
            signed = amount
            if tx_type == "expense":
                signed = -abs(amount)
            elif tx_type == "income":
                signed = abs(amount)
            elif tx_type == "investment":
                signed = -abs(amount)

            title = row.get("description") or row.get("category") or tx_type.capitalize()
            subtitle_bits = [bit for bit in [row.get("date"), tx_type.capitalize(), row.get("account")] if bit]
            rows.append(
                {
                    "id": f"{tx_type}:{row.get('id', '')}",
                    "type": tx_type,
                    "date": tx_date,
                    "date_label": tx_date.isoformat() if tx_date else str(row.get("date", "")),
                    "category": row.get("category", "") or tx_type.capitalize(),
                    "sub_category": row.get("sub_category", ""),
                    "account": row.get("account", ""),
                    "description": title,
                    "subtitle": " · ".join(subtitle_bits),
                    "amount": amount,
                    "signed_amount": signed,
                    "href": f"/transactions?q={row.get('id', '')}",
                    "created_at": row.get("created_at", ""),
                }
            )
    rows.sort(key=lambda item: (item.get("date") or date.min, str(item.get("created_at", ""))), reverse=True)
    return rows


def _days_since(start: date | None, today: date) -> int | None:
    if not start:
        return None
    return max(0, (today - start).days)


def _pending_checks(today: date) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for row in _read_csv(PENDING_CSV):
        status = str(row.get("status", "")).lower()
        if status in {"executed", "paid", "closed", "done"}:
            continue
        due = _parse_date(row.get("date_due"))
        if not due:
            continue
        days = (due - today).days
        if days <= 3:
            tone = "critical" if days <= 0 else "warning"
            label = "Overdue" if days < 0 else "Due today" if days == 0 else "Due soon"
            checks.append(
                {
                    "id": f"pending:{row.get('id', '')}:{due.isoformat()}",
                    "tone": tone,
                    "icon": "🔴" if days <= 0 else "🟡",
                    "label": label,
                    "title": row.get("description") or row.get("category") or "Pending payment",
                    "detail": f"€ {_parse_amount(row.get('amount')):.2f} · {label.lower()} · {due.isoformat()}",
                    "href": "/pending",
                    "priority": 100 - days,
                }
            )
    return checks


def _debt_like_checks(path: Path, kind: str, today: date) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for row in _read_csv(path):
        status = str(row.get("status", "")).lower()
        if status and status not in {"active", "open", "pending"}:
            continue
        start = _parse_date(row.get("start_date")) or _parse_date(row.get("created_at"))
        due = _parse_date(row.get("due_date"))
        age = _days_since(start, today)
        remaining = _parse_amount(row.get("remaining_amount") or row.get("original_amount"))
        due_days = (due - today).days if due else None
        should_show = False
        tone = "info"
        icon = "🔔"
        label = "Review"
        if due_days is not None and due_days <= 7:
            should_show = True
            tone = "critical" if due_days <= 0 else "warning"
            icon = "🔴" if due_days <= 0 else "🟡"
            label = "Due check" if due_days <= 0 else "Due soon"
        elif age is not None and age >= 14:
            should_show = True
            tone = "warning" if age >= 30 else "info"
            icon = "🟡" if age >= 30 else "🟣"
            label = "Old item"
        if not should_show:
            continue
        title = row.get("name") or row.get("description") or kind.capitalize()
        if kind == "debt":
            href = "/debts"
            who = row.get("creditor", "")
        else:
            href = "/payables"
            who = row.get("payee", "")
        detail_bits = [f"€ {remaining:.2f}"]
        if who:
            detail_bits.append(who)
        if age is not None:
            detail_bits.append(f"open for {age} days")
        checks.append(
            {
                "id": f"{kind}:{row.get('id', '')}:{remaining:.2f}",
                "tone": tone,
                "icon": icon,
                "label": label,
                "title": title,
                "detail": " · ".join(detail_bits),
                "href": href,
                "priority": 60 + (age or 0),
            }
        )
    return checks


def _recurring_checks(today: date) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for row in _read_csv(RECURRING_CSV):
        try:
            day = int(str(row.get("day_of_month") or "0"))
        except ValueError:
            continue
        if day <= 0:
            continue
        day = min(day, 28)
        try:
            next_due = today.replace(day=day)
        except ValueError:
            continue
        if next_due < today:
            month = today.month + 1
            year = today.year
            if month > 12:
                month = 1
                year += 1
            next_due = date(year, month, day)
        days = (next_due - today).days
        if days <= 3:
            amount = _parse_amount(row.get("amount"))
            checks.append(
                {
                    "id": f"recurring:{row.get('id', '')}:{next_due.isoformat()}",
                    "tone": "warning" if days else "critical",
                    "icon": "🔁",
                    "label": "Recurring due" if days else "Recurring today",
                    "title": row.get("name") or row.get("category") or "Recurring rule",
                    "detail": f"€ {amount:.2f} · {row.get('type', 'payment')} · {next_due.isoformat()}",
                    "href": "/recurring",
                    "priority": 80 - days,
                }
            )
    return checks


def _money_mood(today_spent: float, week_spent: float, checks: list[dict[str, Any]]) -> dict[str, str]:
    urgent = sum(1 for item in checks if item.get("tone") == "critical")
    warnings = sum(1 for item in checks if item.get("tone") == "warning")
    if urgent or today_spent >= 80:
        return {
            "icon": "🔴",
            "label": "Pressure",
            "title": "Money pressure is high",
            "detail": "Check due items before adding new expenses.",
        }
    if warnings or week_spent >= 180 or today_spent >= 35:
        return {
            "icon": "🟡",
            "label": "Careful",
            "title": "Stay sharp today",
            "detail": "You are fine, but today deserves a bit of control.",
        }
    return {
        "icon": "🟢",
        "label": "Safe",
        "title": "You look safe today",
        "detail": "No heavy spending pressure is visible right now.",
    }


def build_phone_experience_summary(today: date | None = None) -> dict[str, Any]:
    """Build a phone-only JSON summary. Read-only; does not modify backend data."""
    today = today or date.today()
    week_start = today - timedelta(days=6)
    month_start = today.replace(day=1)
    transactions = _transaction_rows()

    expenses = [row for row in transactions if row["type"] == "expense" and row["date"]]
    incomes = [row for row in transactions if row["type"] == "income" and row["date"]]

    today_spent = sum(abs(row["amount"]) for row in expenses if row["date"] == today)
    today_income = sum(abs(row["amount"]) for row in incomes if row["date"] == today)
    week_spent = sum(abs(row["amount"]) for row in expenses if week_start <= row["date"] <= today)
    week_income = sum(abs(row["amount"]) for row in incomes if week_start <= row["date"] <= today)
    month_spent = sum(abs(row["amount"]) for row in expenses if month_start <= row["date"] <= today)

    daily_spending = []
    for offset in range(6, -1, -1):
        day = today - timedelta(days=offset)
        daily_spending.append(
            {
                "label": day.strftime("%a")[:1],
                "date": day.isoformat(),
                "amount": round(sum(abs(row["amount"]) for row in expenses if row["date"] == day), 2),
            }
        )

    category_totals: dict[str, float] = {}
    for row in expenses:
        if not (month_start <= row["date"] <= today):
            continue
        category = str(row.get("category") or "Other")
        category_totals[category] = category_totals.get(category, 0.0) + abs(row["amount"])

    category_spending = [
        {"category": key, "amount": round(value, 2)}
        for key, value in sorted(category_totals.items(), key=lambda item: item[1], reverse=True)[:6]
    ]

    checks = []
    checks.extend(_pending_checks(today))
    checks.extend(_debt_like_checks(DEBTS_CSV, "debt", today))
    checks.extend(_debt_like_checks(PAYABLES_CSV, "payable", today))
    checks.extend(_recurring_checks(today))
    checks.sort(key=lambda item: item.get("priority", 0), reverse=True)

    recent = []
    for row in transactions[:14]:
        recent.append(
            {
                "id": row["id"],
                "type": row["type"],
                "title": row["description"],
                "subtitle": row["subtitle"],
                "category": row["category"],
                "account": row["account"],
                "date": row["date_label"],
                "amount": round(row["amount"], 2),
                "signed_amount": round(row["signed_amount"], 2),
                "href": row["href"],
            }
        )

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "today": today.isoformat(),
        "metrics": {
            "today_spent": round(today_spent, 2),
            "today_income": round(today_income, 2),
            "week_spent": round(week_spent, 2),
            "week_income": round(week_income, 2),
            "month_spent": round(month_spent, 2),
            "smart_check_count": len(checks),
        },
        "daily_spending": daily_spending,
        "category_spending": category_spending,
        "smart_checks": checks[:8],
        "recent": recent,
        "mood": _money_mood(today_spent, week_spent, checks),
        "quick_actions": [
            {"label": "Add expense", "href": "/add?type=expense", "icon": "💸"},
            {"label": "Add income", "href": "/add?type=income", "icon": "💰"},
            {"label": "Open logs", "href": "/transactions", "icon": "≡"},
            {"label": "Plan", "href": "/pending", "icon": "◷"},
        ],
    }


def build_phone_experience_summary_cached(today: date | None = None) -> dict[str, Any]:
    """Cached read-only phone summary.

    The phone app asks for this data on load. Caching prevents the app from
    re-reading all CSV files on every navigation/reload while still refreshing
    when source data or the day changes.
    """
    today = today or date.today()
    try:
        from money_manager.services.cache_service import cached_calculation

        return cached_calculation(
            "phone.experience.summary",
            lambda: build_phone_experience_summary(today),
            extra_fingerprint={"today": today.isoformat()},
            allow_stale_on_error=True,
        )
    except Exception:
        return build_phone_experience_summary(today)
