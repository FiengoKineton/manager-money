from __future__ import annotations

from datetime import date, datetime
from math import ceil
from typing import Any, Mapping

from money_manager.config.user_paths import user_data_path
from money_manager.security.secure_storage import read_json_secure, write_json_secure

SAVINGS_GOAL_STATUS_ACTIVE = "active"
SAVINGS_GOAL_STATUS_COMPLETED = "completed"
SAVINGS_GOAL_STATUS_PAUSED = "paused"
SAVINGS_GOAL_STATUS_ARCHIVED = "archived"
SAVINGS_GOAL_STATUS_OPTIONS = [
    (SAVINGS_GOAL_STATUS_ACTIVE, "Active"),
    (SAVINGS_GOAL_STATUS_COMPLETED, "Completed"),
    (SAVINGS_GOAL_STATUS_PAUSED, "Paused"),
    (SAVINGS_GOAL_STATUS_ARCHIVED, "Archived"),
]
_VALID_STATUSES = {value for value, _label in SAVINGS_GOAL_STATUS_OPTIONS}


def _path(user_id: str | None = None):
    return user_data_path("savings_goals.json", user_id=user_id)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _default_payload() -> dict[str, Any]:
    return {"schema_version": 1, "goals": [], "events": [], "updated_at": ""}


def load_savings_goals(user_id: str | None = None) -> dict[str, Any]:
    payload = read_json_secure(_path(user_id), default=None, user_id=user_id)
    if not isinstance(payload, dict):
        payload = _default_payload()
    goals = [_normalize_goal(row) for row in payload.get("goals", []) if isinstance(row, Mapping)]
    events = [dict(row) for row in payload.get("events", []) if isinstance(row, Mapping)]
    return {"schema_version": 1, "goals": goals, "events": events[-500:], "updated_at": str(payload.get("updated_at") or "")}


def save_savings_goals(payload: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    normalized = _default_payload()
    normalized.update(dict(payload or {}))
    normalized["goals"] = [_normalize_goal(row) for row in normalized.get("goals", []) if isinstance(row, Mapping)]
    normalized["events"] = [dict(row) for row in normalized.get("events", []) if isinstance(row, Mapping)][-500:]
    normalized["updated_at"] = _now()
    write_json_secure(_path(user_id), normalized, user_id=user_id)
    return normalized


def page_context(*, message: str = "", error: str = "", user_id: str | None = None) -> dict[str, Any]:
    payload = load_savings_goals(user_id=user_id)
    goals = [_decorate_goal(row) for row in payload.get("goals", [])]
    active_goals = [row for row in goals if row.get("status") in {SAVINGS_GOAL_STATUS_ACTIVE, SAVINGS_GOAL_STATUS_PAUSED}]
    completed_goals = [row for row in goals if row.get("status") == SAVINGS_GOAL_STATUS_COMPLETED]
    archived_goals = [row for row in goals if row.get("status") == SAVINGS_GOAL_STATUS_ARCHIVED]
    active_goals.sort(key=lambda row: (row.get("due_date_sort") or "9999-99-99", -row.get("progress", 0), row.get("title", "").casefold()))
    completed_goals.sort(key=lambda row: row.get("updated_at", ""), reverse=True)
    archived_goals.sort(key=lambda row: row.get("updated_at", ""), reverse=True)
    return {
        "message": message,
        "error": error,
        "goals": goals,
        "active_goals": active_goals,
        "completed_goals": completed_goals,
        "archived_goals": archived_goals,
        "goal_status_options": SAVINGS_GOAL_STATUS_OPTIONS,
        "goal_totals": _totals(goals),
        "today": date.today().isoformat(),
    }


def dashboard_goal_cards(limit: int = 3, user_id: str | None = None) -> list[dict[str, Any]]:
    goals = [_decorate_goal(row) for row in load_savings_goals(user_id=user_id).get("goals", [])]
    active = [row for row in goals if row.get("status") == SAVINGS_GOAL_STATUS_ACTIVE]
    active.sort(key=lambda row: (row.get("due_date_sort") or "9999-99-99", -row.get("progress", 0), row.get("title", "").casefold()))
    return active[: max(0, int(limit or 0))]


def create_goal_from_form(form: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    title = _clean_text(form.get("title") or form.get("goal_title") or form.get("name"))
    target = _money(form.get("target_amount") or form.get("goal_target_amount"))
    if not title:
        return {"ok": False, "error": "Insert a goal name."}
    if target <= 0:
        return {"ok": False, "error": "Insert a target amount greater than zero."}
    payload = load_savings_goals(user_id=user_id)
    current = min(_money(form.get("current_amount") or form.get("goal_current_amount")), target)
    status = _status(form.get("status") or SAVINGS_GOAL_STATUS_ACTIVE, current=current, target=target)
    row = _normalize_goal({
        "id": _new_id(payload.get("goals", [])),
        "title": title,
        "target_amount": target,
        "current_amount": current,
        "monthly_contribution": _money(form.get("monthly_contribution") or form.get("goal_monthly_contribution")),
        "due_date": _clean_date(form.get("due_date") or form.get("goal_due_date")),
        "category": _clean_text(form.get("category") or form.get("goal_category") or "Savings"),
        "account_id": _clean_text(form.get("account_id") or form.get("goal_account_id")),
        "description": _clean_multiline(form.get("description") or form.get("goal_description")),
        "status": status,
        "created_at": _now(),
        "updated_at": _now(),
        "completed_at": _now() if status == SAVINGS_GOAL_STATUS_COMPLETED else "",
    })
    payload["goals"] = [*payload.get("goals", []), row]
    payload["events"] = [*payload.get("events", []), _event(row, "create", f"Created savings goal {title}")][-500:]
    save_savings_goals(payload, user_id=user_id)
    return {"ok": True, "message": f"{title} saved.", "goal": row}


def update_goal_from_form(form: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    goal_id = _clean_text(form.get("id"))
    payload = load_savings_goals(user_id=user_id)
    index, row = _find_goal(payload, goal_id)
    if row is None:
        return {"ok": False, "error": "Goal not found."}
    title = _clean_text(form.get("title") or row.get("title"))
    target = _money(form.get("target_amount"), default=_money(row.get("target_amount")))
    current = min(_money(form.get("current_amount"), default=_money(row.get("current_amount"))), target)
    row.update({
        "title": title or row.get("title", "Savings goal"),
        "target_amount": target,
        "current_amount": current,
        "monthly_contribution": _money(form.get("monthly_contribution"), default=_money(row.get("monthly_contribution"))),
        "due_date": _clean_date(form.get("due_date")) if "due_date" in form else row.get("due_date", ""),
        "category": _clean_text(form.get("category") or row.get("category")),
        "account_id": _clean_text(form.get("account_id") or row.get("account_id")),
        "description": _clean_multiline(form.get("description") if "description" in form else row.get("description")),
        "status": _status(form.get("status") or row.get("status"), current=current, target=target),
        "updated_at": _now(),
    })
    if row["status"] == SAVINGS_GOAL_STATUS_COMPLETED and not row.get("completed_at"):
        row["completed_at"] = _now()
    if row["status"] != SAVINGS_GOAL_STATUS_COMPLETED:
        row["completed_at"] = ""
    payload["goals"][index] = _normalize_goal(row)
    payload["events"] = [*payload.get("events", []), _event(row, "update", row.get("title", ""))][-500:]
    save_savings_goals(payload, user_id=user_id)
    return {"ok": True, "message": f"{row.get('title', 'Goal')} updated."}


def add_contribution_from_form(form: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    goal_id = _clean_text(form.get("id"))
    amount = _money(form.get("amount") or form.get("contribution_amount"))
    if amount <= 0:
        return {"ok": False, "error": "Insert a contribution greater than zero."}
    payload = load_savings_goals(user_id=user_id)
    index, row = _find_goal(payload, goal_id)
    if row is None:
        return {"ok": False, "error": "Goal not found."}
    target = _money(row.get("target_amount"))
    row["current_amount"] = min(target, _money(row.get("current_amount")) + amount)
    row["status"] = _status(row.get("status"), current=row["current_amount"], target=target)
    row["updated_at"] = _now()
    if row["status"] == SAVINGS_GOAL_STATUS_COMPLETED:
        row["completed_at"] = row.get("completed_at") or _now()
    payload["goals"][index] = _normalize_goal(row)
    payload["events"] = [*payload.get("events", []), _event(row, "contribution", f"Added {amount:.2f}")][-500:]
    save_savings_goals(payload, user_id=user_id)
    return {"ok": True, "message": f"Contribution added to {row.get('title', 'goal')}."}


def delete_goal_from_form(form: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    goal_id = _clean_text(form.get("id"))
    payload = load_savings_goals(user_id=user_id)
    before = len(payload.get("goals", []))
    payload["goals"] = [row for row in payload.get("goals", []) if str(row.get("id")) != goal_id]
    if len(payload["goals"]) == before:
        return {"ok": False, "error": "Goal not found."}
    save_savings_goals(payload, user_id=user_id)
    return {"ok": True, "message": "Goal deleted."}


def _normalize_goal(row: Mapping[str, Any]) -> dict[str, Any]:
    target = _money(row.get("target_amount"))
    current = min(_money(row.get("current_amount")), target) if target > 0 else _money(row.get("current_amount"))
    return {
        "id": _clean_text(row.get("id")),
        "title": _clean_text(row.get("title") or row.get("name") or "Savings goal"),
        "target_amount": target,
        "current_amount": current,
        "monthly_contribution": _money(row.get("monthly_contribution")),
        "due_date": _clean_date(row.get("due_date")),
        "category": _clean_text(row.get("category") or "Savings"),
        "account_id": _clean_text(row.get("account_id")),
        "description": _clean_multiline(row.get("description")),
        "status": _status(row.get("status"), current=current, target=target),
        "created_at": _clean_text(row.get("created_at")),
        "updated_at": _clean_text(row.get("updated_at")),
        "completed_at": _clean_text(row.get("completed_at")),
    }


def _decorate_goal(row: Mapping[str, Any]) -> dict[str, Any]:
    item = _normalize_goal(row)
    target = _money(item.get("target_amount"))
    current = _money(item.get("current_amount"))
    remaining = max(0.0, target - current)
    progress = 100.0 if target <= 0 and current > 0 else (min(100.0, current / target * 100.0) if target > 0 else 0.0)
    monthly = _money(item.get("monthly_contribution"))
    months_left = ceil(remaining / monthly) if monthly > 0 and remaining > 0 else 0
    due = _date(item.get("due_date"))
    if item.get("status") == SAVINGS_GOAL_STATUS_COMPLETED:
        tone = "completed"
    elif due and due < date.today() and remaining > 0:
        tone = "late"
    elif progress >= 75:
        tone = "good"
    else:
        tone = "neutral"
    item.update({
        "remaining_amount": remaining,
        "progress": round(progress, 1),
        "progress_label": f"{progress:.0f}%",
        "monthly_contribution_label": f"€ {monthly:.2f}" if monthly > 0 else "No monthly plan",
        "months_left": months_left,
        "months_left_label": f"{months_left} month{'s' if months_left != 1 else ''}" if months_left else "No contribution plan" if remaining > 0 else "Complete",
        "status_label": dict(SAVINGS_GOAL_STATUS_OPTIONS).get(item.get("status"), "Active"),
        "due_date_sort": due.isoformat() if due else "",
        "due_label": due.isoformat() if due else "No due date",
        "tone": tone,
    })
    return item


def _totals(goals: list[dict[str, Any]]) -> dict[str, Any]:
    decorated = [_decorate_goal(row) for row in goals]
    active = [row for row in decorated if row.get("status") == SAVINGS_GOAL_STATUS_ACTIVE]
    target = sum(_money(row.get("target_amount")) for row in active)
    current = sum(_money(row.get("current_amount")) for row in active)
    remaining = max(0.0, target - current)
    monthly = sum(_money(row.get("monthly_contribution")) for row in active)
    return {
        "active_count": len(active),
        "completed_count": sum(1 for row in decorated if row.get("status") == SAVINGS_GOAL_STATUS_COMPLETED),
        "target_amount": target,
        "current_amount": current,
        "remaining_amount": remaining,
        "monthly_contribution": monthly,
        "overall_progress": round((current / target * 100.0) if target > 0 else 0.0, 1),
    }


def _find_goal(payload: Mapping[str, Any], goal_id: str) -> tuple[int, dict[str, Any] | None]:
    for index, row in enumerate(payload.get("goals", [])):
        if str(row.get("id")) == str(goal_id):
            return index, dict(row)
    return -1, None


def _new_id(rows: list[Mapping[str, Any]]) -> str:
    numbers = []
    for row in rows:
        try:
            numbers.append(int(float(row.get("id") or 0)))
        except Exception:
            continue
    return str((max(numbers) if numbers else 0) + 1)


def _event(goal: Mapping[str, Any], action: str, detail: str = "") -> dict[str, Any]:
    return {"at": _now(), "goal_id": str(goal.get("id") or ""), "action": action, "detail": detail}


def _status(value: Any, *, current: float = 0.0, target: float = 0.0) -> str:
    if target > 0 and current >= target - 0.005:
        return SAVINGS_GOAL_STATUS_COMPLETED
    status = str(value or SAVINGS_GOAL_STATUS_ACTIVE).strip().casefold().replace(" ", "_")
    return status if status in _VALID_STATUSES else SAVINGS_GOAL_STATUS_ACTIVE


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _clean_multiline(value: Any) -> str:
    return "\n".join(line.strip() for line in str(value or "").replace("\r", "").split("\n") if line.strip())


def _clean_date(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        return date.fromisoformat(raw).isoformat()
    except Exception:
        return ""


def _date(value: Any) -> date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except Exception:
        return None


def _money(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, float(str(value if value is not None else default).replace(",", ".")))
    except Exception:
        return max(0.0, float(default or 0.0))
