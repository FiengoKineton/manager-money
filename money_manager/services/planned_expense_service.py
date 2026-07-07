from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping

from money_manager.config.user_paths import user_data_path
from money_manager.security.secure_storage import read_json_secure, write_json_secure
from money_manager.services.payment_form_service import account_options_for_payment_forms, payment_form_context
from money_manager.services.transaction_service import save_transaction_payload

STATUS_ACTIVE = "active"
STATUS_PAID = "paid"
STATUS_CANCELLED = "cancelled"
STATUS_ARCHIVED = "archived"
PLANNED_EXPENSE_STATUS_OPTIONS = [
    (STATUS_ACTIVE, "Active"),
    (STATUS_PAID, "Paid"),
    (STATUS_CANCELLED, "Cancelled"),
    (STATUS_ARCHIVED, "Archived"),
]
_VALID_STATUSES = {value for value, _label in PLANNED_EXPENSE_STATUS_OPTIONS}


def _path(user_id: str | None = None):
    return user_data_path("planned_expenses.json", user_id=user_id)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _default_payload() -> dict[str, Any]:
    return {"schema_version": 1, "planned_expenses": [], "events": [], "updated_at": ""}


def load_planned_expenses(user_id: str | None = None) -> dict[str, Any]:
    payload = read_json_secure(_path(user_id), default=None, user_id=user_id)
    if not isinstance(payload, dict):
        payload = _default_payload()
    rows = [_normalize(row) for row in payload.get("planned_expenses", []) if isinstance(row, Mapping)]
    events = [dict(row) for row in payload.get("events", []) if isinstance(row, Mapping)]
    return {"schema_version": 1, "planned_expenses": rows, "events": events[-500:], "updated_at": str(payload.get("updated_at") or "")}


def save_planned_expenses(payload: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    normalized = _default_payload()
    normalized.update(dict(payload or {}))
    normalized["planned_expenses"] = [_normalize(row) for row in normalized.get("planned_expenses", []) if isinstance(row, Mapping)]
    normalized["events"] = [dict(row) for row in normalized.get("events", []) if isinstance(row, Mapping)][-500:]
    normalized["updated_at"] = _now()
    write_json_secure(_path(user_id), normalized, user_id=user_id)
    return normalized


def page_context(*, message: str = "", error: str = "", user_id: str | None = None) -> dict[str, Any]:
    payload = load_planned_expenses(user_id=user_id)
    rows = [_decorate(row) for row in payload.get("planned_expenses", [])]
    active = [row for row in rows if row.get("status") == STATUS_ACTIVE]
    closed = [row for row in rows if row.get("status") in {STATUS_PAID, STATUS_CANCELLED, STATUS_ARCHIVED}]
    active.sort(key=lambda row: (row.get("due_date_sort") or "9999-99-99", row.get("title", "").casefold()))
    closed.sort(key=lambda row: row.get("updated_at", ""), reverse=True)
    return {
        "message": message,
        "error": error,
        "planned_expenses": rows,
        "active_planned_expenses": active,
        "closed_planned_expenses": closed,
        "planned_expense_status_options": PLANNED_EXPENSE_STATUS_OPTIONS,
        "planned_expense_totals": _totals(rows),
        "today": date.today().isoformat(),
        "account_options": account_options_for_payment_forms(include_credit=True),
        **payment_form_context("expense"),
    }


def active_planned_expenses_for_forecast(user_id: str | None = None) -> list[dict[str, Any]]:
    rows = [_decorate(row) for row in load_planned_expenses(user_id=user_id).get("planned_expenses", [])]
    active = [row for row in rows if row.get("status") == STATUS_ACTIVE and row.get("remaining_amount", 0.0) > 0]
    active.sort(key=lambda row: (row.get("due_date_sort") or "9999-99-99", row.get("title", "").casefold()))
    return active


def upcoming_planned_expense_reminders(limit: int = 8, user_id: str | None = None) -> list[dict[str, Any]]:
    return active_planned_expenses_for_forecast(user_id=user_id)[: max(0, int(limit or 0))]


def create_planned_expense_from_form(form: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    title = _clean_text(form.get("title") or form.get("name"))
    expected = _money(form.get("expected_amount") or form.get("original_amount") or form.get("amount"))
    if not title:
        return {"ok": False, "error": "Insert a planned expense name."}
    if expected <= 0:
        return {"ok": False, "error": "Insert an expected amount greater than zero."}
    payload = load_planned_expenses(user_id=user_id)
    paid = min(_money(form.get("paid_amount")), expected)
    status = _status(form.get("status") or STATUS_ACTIVE, paid=paid, expected=expected)
    row = _normalize({
        "id": _new_id(payload.get("planned_expenses", [])),
        "title": title,
        "vendor": _clean_text(form.get("vendor")),
        "expected_amount": expected,
        "paid_amount": paid,
        "category": _clean_text(form.get("category") or "Planned"),
        "account_id": _clean_text(form.get("account_id") or form.get("account")),
        "payment_method_id": _clean_text(form.get("payment_method_id") or form.get("preferred_payment_method_id")),
        "due_date": _clean_date(form.get("due_date")),
        "description": _clean_multiline(form.get("description")),
        "status": status,
        "created_at": _now(),
        "updated_at": _now(),
        "closed_at": _now() if status != STATUS_ACTIVE else "",
        "linked_transaction_uid": "",
    })
    payload["planned_expenses"] = [*payload.get("planned_expenses", []), row]
    payload["events"] = [*payload.get("events", []), _event(row, "create", f"Created planned expense {title}")][-500:]
    save_planned_expenses(payload, user_id=user_id)
    return {"ok": True, "message": f"{title} saved.", "planned_expense": row}


def update_planned_expense_from_form(form: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    item_id = _clean_text(form.get("id"))
    payload = load_planned_expenses(user_id=user_id)
    index, row = _find(payload, item_id)
    if row is None:
        return {"ok": False, "error": "Planned expense not found."}
    expected = _money(form.get("expected_amount"), default=_money(row.get("expected_amount")))
    paid = min(_money(form.get("paid_amount"), default=_money(row.get("paid_amount"))), expected)
    status = _status(form.get("status") or row.get("status"), paid=paid, expected=expected)
    row.update({
        "title": _clean_text(form.get("title") or row.get("title") or "Planned expense"),
        "vendor": _clean_text(form.get("vendor") or row.get("vendor")),
        "expected_amount": expected,
        "paid_amount": paid,
        "category": _clean_text(form.get("category") or row.get("category") or "Planned"),
        "account_id": _clean_text(form.get("account_id") or form.get("account") or row.get("account_id")),
        "payment_method_id": _clean_text(form.get("payment_method_id") or row.get("payment_method_id")),
        "due_date": _clean_date(form.get("due_date")) if "due_date" in form else row.get("due_date", ""),
        "description": _clean_multiline(form.get("description") if "description" in form else row.get("description")),
        "status": status,
        "updated_at": _now(),
    })
    if status != STATUS_ACTIVE and not row.get("closed_at"):
        row["closed_at"] = _now()
    if status == STATUS_ACTIVE:
        row["closed_at"] = ""
    payload["planned_expenses"][index] = _normalize(row)
    payload["events"] = [*payload.get("events", []), _event(row, "update", row.get("title", ""))][-500:]
    save_planned_expenses(payload, user_id=user_id)
    return {"ok": True, "message": f"{row.get('title', 'Planned expense')} updated."}


def mark_planned_expense_paid_from_form(form: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    item_id = _clean_text(form.get("id"))
    payload = load_planned_expenses(user_id=user_id)
    index, row = _find(payload, item_id)
    if row is None:
        return {"ok": False, "error": "Planned expense not found."}
    expected = _money(row.get("expected_amount"))
    remaining = max(0.0, expected - _money(row.get("paid_amount")))
    amount = _money(form.get("amount"), default=remaining) or remaining
    amount = min(amount, remaining)
    if amount <= 0:
        return {"ok": False, "error": "Nothing left to pay."}
    save_result = save_transaction_payload(
        {
            "type": "expense",
            "date": form.get("date") or date.today().isoformat(),
            "category": row.get("category") or "Planned",
            "sub_category": row.get("title") or "Planned expense",
            "amount": amount,
            "account": form.get("account") or row.get("account_id") or "",
            "account_id": form.get("account_id") or row.get("account_id") or form.get("account") or "",
            "payment_method_id": form.get("payment_method_id") or row.get("payment_method_id") or "",
            "description": form.get("description") or f"Planned expense: {row.get('title', '')}",
        },
        account_id=form.get("account_id") or row.get("account_id") or form.get("account") or "",
        payment_method_id=form.get("payment_method_id") or row.get("payment_method_id") or "",
        payment_method=form.get("account_payment_method", ""),
        insufficient_action=form.get("account_insufficient_action", ""),
    )
    if isinstance(save_result, dict) and not save_result.get("ok", True):
        return save_result
    row["paid_amount"] = min(expected, _money(row.get("paid_amount")) + amount)
    if row["paid_amount"] >= expected - 0.005:
        row["status"] = STATUS_PAID
        row["closed_at"] = _now()
    row["updated_at"] = _now()
    if isinstance(save_result, dict):
        row["linked_transaction_uid"] = str(save_result.get("transaction_uid") or save_result.get("id") or row.get("linked_transaction_uid") or "")
    payload["planned_expenses"][index] = _normalize(row)
    payload["events"] = [*payload.get("events", []), _event(row, "payment", f"Paid {amount:.2f}")][-500:]
    save_planned_expenses(payload, user_id=user_id)
    return {"ok": True, "message": f"{row.get('title', 'Planned expense')} paid.", "paid_amount": amount}


def delete_planned_expense_from_form(form: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    item_id = _clean_text(form.get("id"))
    payload = load_planned_expenses(user_id=user_id)
    before = len(payload.get("planned_expenses", []))
    payload["planned_expenses"] = [row for row in payload.get("planned_expenses", []) if str(row.get("id")) != item_id]
    if len(payload["planned_expenses"]) == before:
        return {"ok": False, "error": "Planned expense not found."}
    save_planned_expenses(payload, user_id=user_id)
    return {"ok": True, "message": "Planned expense deleted."}


def _normalize(row: Mapping[str, Any]) -> dict[str, Any]:
    expected = _money(row.get("expected_amount") or row.get("original_amount"))
    paid = min(_money(row.get("paid_amount")), expected)
    return {
        "id": _clean_text(row.get("id")),
        "title": _clean_text(row.get("title") or row.get("name") or "Planned expense"),
        "vendor": _clean_text(row.get("vendor")),
        "expected_amount": expected,
        "paid_amount": paid,
        "category": _clean_text(row.get("category") or "Planned"),
        "account_id": _clean_text(row.get("account_id") or row.get("account")),
        "payment_method_id": _clean_text(row.get("payment_method_id") or row.get("preferred_payment_method_id")),
        "due_date": _clean_date(row.get("due_date")),
        "description": _clean_multiline(row.get("description")),
        "status": _status(row.get("status"), paid=paid, expected=expected),
        "created_at": _clean_text(row.get("created_at")),
        "updated_at": _clean_text(row.get("updated_at")),
        "closed_at": _clean_text(row.get("closed_at")),
        "linked_transaction_uid": _clean_text(row.get("linked_transaction_uid")),
    }


def _decorate(row: Mapping[str, Any]) -> dict[str, Any]:
    item = _normalize(row)
    expected = _money(item.get("expected_amount"))
    paid = _money(item.get("paid_amount"))
    remaining = max(0.0, expected - paid)
    progress = min(100.0, paid / expected * 100.0) if expected > 0 else 0.0
    due = _date(item.get("due_date"))
    if item.get("status") == STATUS_PAID:
        tone = "paid"
    elif due and due < date.today() and remaining > 0:
        tone = "late"
    elif due and (due - date.today()).days <= 7:
        tone = "warning"
    else:
        tone = "neutral"
    item.update({
        "remaining_amount": remaining,
        "progress": round(progress, 1),
        "progress_label": f"{progress:.0f}%",
        "status_label": dict(PLANNED_EXPENSE_STATUS_OPTIONS).get(item.get("status"), "Active"),
        "due_date_sort": due.isoformat() if due else "",
        "due_label": _due_label(due),
        "tone": tone,
    })
    return item


def _totals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    decorated = [_decorate(row) for row in rows]
    active = [row for row in decorated if row.get("status") == STATUS_ACTIVE]
    expected = sum(_money(row.get("expected_amount")) for row in active)
    paid = sum(_money(row.get("paid_amount")) for row in active)
    remaining = sum(_money(row.get("remaining_amount")) for row in active)
    return {
        "active_count": len(active),
        "closed_count": len(decorated) - len(active),
        "expected_amount": expected,
        "paid_amount": paid,
        "remaining_amount": remaining,
    }


def _find(payload: Mapping[str, Any], item_id: str) -> tuple[int, dict[str, Any] | None]:
    for index, row in enumerate(payload.get("planned_expenses", [])):
        if str(row.get("id")) == str(item_id):
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


def _event(item: Mapping[str, Any], action: str, detail: str = "") -> dict[str, Any]:
    return {"at": _now(), "planned_expense_id": str(item.get("id") or ""), "action": action, "detail": detail}


def _status(value: Any, *, paid: float = 0.0, expected: float = 0.0) -> str:
    if expected > 0 and paid >= expected - 0.005:
        return STATUS_PAID
    status = str(value or STATUS_ACTIVE).strip().casefold().replace(" ", "_")
    return status if status in _VALID_STATUSES else STATUS_ACTIVE


def _due_label(due: date | None) -> str:
    if due is None:
        return "No due date"
    today = date.today()
    delta = (due - today).days
    if delta == 0:
        return "Today"
    if delta == 1:
        return "Tomorrow"
    if delta < 0:
        return f"{abs(delta)}d late"
    if delta <= 30:
        return f"In {delta}d"
    return due.isoformat()


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
