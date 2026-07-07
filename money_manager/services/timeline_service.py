from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from flask import url_for

from money_manager.config.paths import TIMELINE_EVENTS_JSON
from money_manager.security.secure_storage import read_json_secure, write_json_secure
from money_manager.services.transaction_service import load_transactions


_OBJECT_LABELS = {
    "debt": "Debt",
    "payable": "Payable",
    "receivable": "Receivable",
    "recurring": "Recurring rule",
    "planned_expense": "Planned expense",
    "savings_goal": "Savings goal",
}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _payload() -> dict[str, Any]:
    payload = read_json_secure(TIMELINE_EVENTS_JSON, default=None)
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("schema_version", 1)
    payload.setdefault("events", [])
    payload.setdefault("updated_at", "")
    if not isinstance(payload["events"], list):
        payload["events"] = []
    return payload


def _save(payload: Mapping[str, Any]) -> None:
    data = dict(payload)
    data["updated_at"] = _now()
    write_json_secure(TIMELINE_EVENTS_JSON, data)


def record_event(
    object_type: str,
    object_id: str | int,
    action: str,
    title: str,
    detail: str = "",
    *,
    amount: float | None = None,
    transaction_type: str = "",
    transaction_id: str | int = "",
    transaction_uid: str = "",
    account_id: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> None:
    object_type = str(object_type or "").strip().casefold()
    object_id = str(object_id or "").strip()
    if not object_type or not object_id:
        return
    payload = _payload()
    events = payload.setdefault("events", [])
    event_id = f"{object_type}:{object_id}:{len(events) + 1}:{datetime.now().timestamp():.6f}"
    events.append({
        "id": event_id,
        "object_type": object_type,
        "object_id": object_id,
        "action": str(action or "event"),
        "title": str(title or "Event"),
        "detail": str(detail or ""),
        "amount": "" if amount is None else f"{float(amount):.2f}",
        "transaction_type": str(transaction_type or ""),
        "transaction_id": str(transaction_id or ""),
        "transaction_uid": str(transaction_uid or ""),
        "account_id": str(account_id or ""),
        "metadata": dict(metadata or {}),
        "created_at": _now(),
    })
    # Keep the file bounded without destroying recent history.
    if len(events) > 5000:
        payload["events"] = events[-5000:]
    _save(payload)


def record_created(object_type: str, object_id: str | int, name: str = "") -> None:
    record_event(object_type, object_id, "created", f"Created {name or _OBJECT_LABELS.get(object_type, object_type)}")


def record_deleted(object_type: str, object_id: str | int, name: str = "") -> None:
    record_event(object_type, object_id, "deleted", f"Deleted {name or _OBJECT_LABELS.get(object_type, object_type)}")


def record_status_change(object_type: str, object_id: str | int, old: str, new: str) -> None:
    old_text = str(old or "").strip() or "blank"
    new_text = str(new or "").strip() or "blank"
    if old_text == new_text:
        return
    record_event(object_type, object_id, "status_changed", f"Status changed from {old_text} to {new_text}")


def record_amount_change(object_type: str, object_id: str | int, field: str, old: Any, new: Any) -> None:
    try:
        old_val = float(str(old or 0).replace(",", "."))
        new_val = float(str(new or 0).replace(",", "."))
    except (TypeError, ValueError):
        return
    if abs(old_val - new_val) <= 0.005:
        return
    label = "Remaining" if field == "remaining_amount" else "Original amount" if field == "original_amount" else field.replace("_", " ").title()
    record_event(object_type, object_id, "amount_changed", f"{label} changed from €{old_val:.2f} to €{new_val:.2f}")


def record_payment(
    object_type: str,
    object_id: str | int,
    amount: float,
    account_id: str = "",
    transaction_type: str = "",
    transaction_id: str | int = "",
    transaction_uid: str = "",
    title: str = "",
) -> None:
    account_label = str(account_id or "").strip() or "selected account"
    record_event(
        object_type,
        object_id,
        "payment_added",
        title or f"Payment added: €{float(amount):.2f}",
        f"Recorded from {account_label}.",
        amount=float(amount),
        transaction_type=transaction_type,
        transaction_id=transaction_id,
        transaction_uid=transaction_uid,
        account_id=account_id,
    )


def record_update_diff(object_type: str, object_id: str | int, before: Mapping[str, Any] | None, after: Mapping[str, Any] | None) -> None:
    before = dict(before or {})
    after = dict(after or {})
    if not before or not after:
        return
    record_status_change(object_type, object_id, before.get("status", ""), after.get("status", ""))
    for field in ("original_amount", "remaining_amount"):
        record_amount_change(object_type, object_id, field, before.get(field), after.get(field))
    for field, label in (("due_date", "Due date"), ("description", "Note"), ("account_id", "Account"), ("preferred_payment_method_id", "Preferred payment method")):
        old = str(before.get(field, "") or "").strip()
        new = str(after.get(field, "") or "").strip()
        if old != new:
            record_event(object_type, object_id, f"{field}_changed", f"{label} changed", f"{old or 'blank'} → {new or 'blank'}")


def events_for_object(object_type: str, object_id: str | int, *, limit: int = 20) -> list[dict[str, Any]]:
    object_type = str(object_type or "").strip().casefold()
    object_id = str(object_id or "").strip()
    events = [row for row in _payload().get("events", []) if str(row.get("object_type")) == object_type and str(row.get("object_id")) == object_id]
    events.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
    return events[:max(0, int(limit or 0))]


def linked_transactions_for_object(object_type: str, object_id: str | int, *, limit: int = 20) -> list[dict[str, Any]]:
    object_type = str(object_type or "").strip().casefold()
    object_id = str(object_id or "").strip()
    if not object_type or not object_id:
        return []
    try:
        df = load_transactions()
    except Exception:
        return []
    if df is None or df.empty:
        return []
    rows = []
    for row_index, row in df.reset_index().iterrows():
        row_type = str(row.get("linked_object_type", "") or "").strip().casefold()
        row_id = str(row.get("linked_object_id", "") or "").strip()
        if row_type != object_type or row_id != object_id:
            continue
        amount = _to_float(row.get("amount"))
        rows.append({
            "row_index": int(row.get("index", row_index)),
            "id": str(row.get("id", "")),
            "transaction_uid": str(row.get("transaction_uid", "")),
            "type": str(row.get("type", "")),
            "date": str(row.get("date", ""))[:10],
            "amount": amount,
            "amount_label": f"€ {amount:.2f}",
            "category": str(row.get("category", "")),
            "description": str(row.get("description", "")),
            "account_label": str(row.get("account_name_snapshot") or row.get("account") or row.get("account_id") or ""),
            "href": _transaction_href(int(row.get("index", row_index))),
        })
    rows.sort(key=lambda item: (item.get("date") or "", item.get("id") or ""), reverse=True)
    return rows[:max(0, int(limit or 0))]


def enrich_object_row(row: dict[str, Any], object_type: str) -> dict[str, Any]:
    object_id = row.get("id", "")
    events = events_for_object(object_type, object_id, limit=8)
    linked = linked_transactions_for_object(object_type, object_id, limit=8)
    row["timeline_events"] = events
    row["linked_transactions"] = linked
    payments = [event for event in events if event.get("action") == "payment_added"]
    row["payment_history"] = payments
    row["timeline_text"] = _timeline_text(events)
    row["payment_history_text"] = _payment_text(payments)
    row["linked_transactions_text"] = _linked_text(linked)
    return row


def transaction_link_summary(tx: Mapping[str, Any]) -> dict[str, Any]:
    object_type = str(tx.get("linked_object_type") or "").strip().casefold()
    object_id = str(tx.get("linked_object_id") or "").strip()
    name = str(tx.get("linked_object_name") or "").strip()
    if not object_type or not object_id:
        return {}
    return {
        "type": object_type,
        "type_label": _OBJECT_LABELS.get(object_type, object_type.replace("_", " ").title()),
        "id": object_id,
        "name": name or f"#{object_id}",
        "href": _object_href(object_type),
    }


def _transaction_href(row_index: int) -> str:
    try:
        return url_for("transactions.transaction_detail", row_index=row_index)
    except RuntimeError:
        return f"/transaction/{row_index}"


def _object_href(object_type: str) -> str:
    endpoints = {
        "debt": "debts.debts_page",
        "payable": "payables.payables_page",
        "receivable": "receivables.receivables_page",
        "recurring": "pending.recurring_page",
        "planned_expense": "planned_expenses.planned_expenses_page",
        "savings_goal": "savings_goals.savings_goals_page",
    }
    endpoint = endpoints.get(object_type)
    if not endpoint:
        return ""
    try:
        return url_for(endpoint)
    except RuntimeError:
        return ""


def _timeline_text(events: list[Mapping[str, Any]]) -> str:
    if not events:
        return "No timeline events yet."
    parts = []
    for event in events[:6]:
        when = str(event.get("created_at") or "")[:10]
        title = str(event.get("title") or "Event")
        parts.append(f"{when} — {title}")
    return " | ".join(parts)


def _payment_text(events: list[Mapping[str, Any]]) -> str:
    if not events:
        return "No payments recorded yet."
    parts = []
    for event in events[:6]:
        when = str(event.get("created_at") or "")[:10]
        amount = str(event.get("amount") or "0.00")
        account = str(event.get("account_id") or "selected account")
        parts.append(f"{when} — €{amount} — {account}")
    return " | ".join(parts)


def _linked_text(rows: list[Mapping[str, Any]]) -> str:
    if not rows:
        return "No linked transactions yet."
    return " | ".join(f"{row.get('date')} — {row.get('amount_label')} — {row.get('description') or row.get('category')}" for row in rows[:6])


def _to_float(value: Any) -> float:
    try:
        return float(str(value or 0).replace(",", "."))
    except (TypeError, ValueError):
        return 0.0
