from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any, Mapping

from money_manager.config.user_paths import get_current_user_id, user_data_path
from money_manager.repositories.pending import delete_pending_for_source, load_pending, update_pending
from money_manager.repositories.recurring import append_recurring, delete_recurring, load_recurring, normalize_amount, update_recurring
from money_manager.security.secure_storage import read_json_secure, write_json_secure
from money_manager.services.contact_service import contact_view, get_contact, list_contacts
from money_manager.services.payment_form_service import (
    account_options_for_payment_forms,
    payment_method_options_for_forms,
    snapshot_account,
    snapshot_payment_method,
)
from money_manager.services.pending_service import execute_pending_by_id, prepare_pending_for_display
from money_manager.services.recurring_service import generate_recurring, next_due_date_for_rule

MANAGED_RECURRING_FILENAME = "managed_recurring_sections.json"
KIND_BILL = "utility_bill"
KIND_WORK_INCOME = "work_income"
MANAGED_KINDS = {KIND_BILL, KIND_WORK_INCOME}

KIND_META = {
    KIND_BILL: {
        "title": "Bollette",
        "singular": "Bolletta",
        "eyebrow": "Utilities and variable bills",
        "description": "Dedicated control page for water, gas, light, internet and other bills. It reuses normal recurring rules, but adds a manual check step before you pay variable amounts.",
        "new_title": "Add bill rule",
        "type": "expense",
        "default_category": "Bollette",
        "default_subtitle": "Water, gas, light, internet, phone or similar recurring bill.",
        "contact_label": "Supplier / company contact",
        "amount_label": "Expected amount (€)",
        "amount_hint": "Use the normal monthly estimate. When the generated pending row arrives, edit the checked amount if the real bill changed.",
        "empty_title": "No bills saved yet.",
        "empty_description": "Add your first bill rule and it will also appear in the normal Recurring page.",
    },
    KIND_WORK_INCOME: {
        "title": "Stipendi / Cedolini",
        "singular": "Cedolino",
        "eyebrow": "Work income checks",
        "description": "Dedicated control page for salary, payslips and recurring work income. It reuses income recurring rules and lets you verify the monthly amount before it is executed.",
        "new_title": "Add salary / payslip rule",
        "type": "income",
        "default_category": "Salary",
        "default_subtitle": "Salary, payslip, collaborator income or monthly company payment.",
        "contact_label": "Employer / company contact",
        "amount_label": "Expected net income (€)",
        "amount_hint": "Use the usual net salary. Update the generated pending row when taxes, reimbursements or variable components change.",
        "empty_title": "No work income rules saved yet.",
        "empty_description": "Add an employer/contact and a monthly amount; the underlying item is still a normal recurring income rule.",
    },
}


def page_context(kind: str, *, message: str = "", error: str = "", user_id: str | None = None) -> dict[str, Any]:
    kind = _clean_kind(kind)
    load_warnings: list[str] = []

    # This page is a normal GET route, so it must render even when automatic
    # recurring generation has a bad/old row or encrypted IO is temporarily busy.
    # The user can still repair the data from the normal Recurring/Pending pages.
    try:
        generate_recurring()
    except Exception as exc:
        load_warnings.append(f"Automatic recurring refresh was skipped: {exc}")

    try:
        payload = load_managed_recurring(user_id=user_id)
    except Exception as exc:
        payload = _normalize_payload({})
        load_warnings.append(f"Dedicated page metadata could not be loaded: {exc}")

    try:
        recurring_by_id = {str(row.get("id") or ""): row for row in load_recurring()}
    except Exception as exc:
        recurring_by_id = {}
        load_warnings.append(f"Recurring rules could not be loaded: {exc}")

    try:
        pending_rows = load_pending()
    except Exception as exc:
        pending_rows = []
        load_warnings.append(f"Pending rows could not be loaded: {exc}")

    items = []
    for item in payload.get("items", []):
        if item.get("kind") != kind:
            continue
        try:
            decorated = _decorate_item(item, recurring_by_id, pending_rows, user_id=user_id)
        except Exception as exc:
            decorated = None
            load_warnings.append(f"A saved item could not be displayed: {exc}")
        if decorated:
            items.append(decorated)

    items.sort(key=lambda row: (row.get("next_due_sort") or "9999-99-99", row.get("title", "").casefold()))
    active_items = [row for row in items if row.get("is_active")]
    archived_items = [row for row in items if not row.get("is_active")]
    pending_open_count = sum(len(row.get("pending_open", [])) for row in active_items)
    due_now_count = sum(1 for row in active_items if row.get("needs_check"))
    monthly_total = 0.0
    for row in active_items:
        try:
            monthly_total += float(row.get("amount_value") or 0.0) / max(1, int(row.get("frequency") or 1))
        except Exception:
            continue

    try:
        companies = [contact_view(contact, show_sensitive_data=True) for contact in list_contacts(include_archived=False) if contact.get("type") == "company"]
    except Exception as exc:
        companies = []
        load_warnings.append(f"Company contacts could not be loaded: {exc}")

    try:
        account_options = account_options_for_payment_forms()
    except Exception as exc:
        account_options = []
        load_warnings.append(f"Account options could not be loaded: {exc}")

    try:
        payment_method_options = payment_method_options_for_forms()
    except Exception as exc:
        payment_method_options = []
        load_warnings.append(f"Payment methods could not be loaded: {exc}")

    combined_error = error
    if load_warnings:
        warning_text = " | ".join(str(item) for item in load_warnings[:4])
        combined_error = f"{combined_error} | {warning_text}" if combined_error else warning_text

    return {
        "meta": KIND_META[kind],
        "kind": kind,
        "message": message,
        "error": combined_error,
        "items": active_items,
        "archived_items": archived_items,
        "contacts": companies,
        "account_options": account_options,
        "payment_method_options": payment_method_options,
        "totals": {
            "active_count": len(active_items),
            "archived_count": len(archived_items),
            "pending_open_count": pending_open_count,
            "due_now_count": due_now_count,
            "monthly_total": round(monthly_total, 2),
            "monthly_total_display": f"{monthly_total:.2f}",
        },
    }


def create_item_from_form(kind: str, form: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    kind = _clean_kind(kind)
    title = _clean_text(form.get("title") or form.get("name"))
    if not title:
        return {"ok": False, "error": "Insert a name."}
    amount = _money(form.get("amount"))
    if amount <= 0:
        return {"ok": False, "error": "Insert an amount greater than zero."}

    rule_id = append_recurring(_recurring_payload_for_kind(kind, form, title=title, amount=amount, user_id=user_id))
    item = _normalize_item({
        "id": _new_id("managed"),
        "kind": kind,
        "title": title,
        "contact_id": _clean_id(form.get("contact_id")),
        "recurring_rule_id": str(rule_id or ""),
        "variable_amount": _truthy(form.get("variable_amount"), default=kind == KIND_BILL),
        "manual_check_required": _truthy(form.get("manual_check_required"), default=True),
        "next_due_amount": _money_text_or_empty(form.get("next_due_amount")),
        "notes": _clean_multiline(form.get("notes")),
        "is_active": True,
        "last_checked_at": "",
        "last_checked_amount": "",
        "last_checked_pending_id": "",
        "created_at": _now(),
        "updated_at": _now(),
        "archived_at": "",
    })
    payload = load_managed_recurring(user_id=user_id)
    payload["items"] = [*payload.get("items", []), item]
    payload["events"] = [*payload.get("events", []), _event(item, "create", f"Created {title}")][-500:]
    save_managed_recurring(payload, user_id=user_id)
    return {"ok": True, "message": f"{title} saved.", "item": item}


def update_item_from_form(item_id: str, form: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    payload = load_managed_recurring(user_id=user_id)
    index, item = _find_item(payload, item_id)
    if item is None:
        return {"ok": False, "error": "Item not found."}

    kind = _clean_kind(item.get("kind"))
    title = _clean_text(form.get("title") or form.get("name"))
    if not title:
        return {"ok": False, "error": "Insert a name."}
    amount = _money(form.get("amount"))
    if amount <= 0:
        return {"ok": False, "error": "Insert an amount greater than zero."}

    rule_id = str(item.get("recurring_rule_id") or "")
    if rule_id:
        delete_pending_for_source("recurring", rule_id, only_pending=True)
        update_recurring(rule_id, _recurring_payload_for_kind(kind, form, title=title, amount=amount, user_id=user_id))
    else:
        rule_id = str(append_recurring(_recurring_payload_for_kind(kind, form, title=title, amount=amount, user_id=user_id)) or "")

    item.update({
        "title": title,
        "contact_id": _clean_id(form.get("contact_id")),
        "recurring_rule_id": rule_id,
        "variable_amount": _truthy(form.get("variable_amount"), default=False),
        "manual_check_required": _truthy(form.get("manual_check_required"), default=True),
        "next_due_amount": _money_text_or_empty(form.get("next_due_amount")),
        "notes": _clean_multiline(form.get("notes")),
        "updated_at": _now(),
    })
    payload["items"][index] = _normalize_item(item)
    payload["events"] = [*payload.get("events", []), _event(payload["items"][index], "update", f"Updated {title}")][-500:]
    save_managed_recurring(payload, user_id=user_id)
    return {"ok": True, "message": f"{title} updated."}


def archive_item(item_id: str, *, archived: bool = True, user_id: str | None = None) -> dict[str, Any]:
    payload = load_managed_recurring(user_id=user_id)
    index, item = _find_item(payload, item_id)
    if item is None:
        return {"ok": False, "error": "Item not found."}
    item["is_active"] = not archived
    item["archived_at"] = _now() if archived else ""
    item["updated_at"] = _now()
    payload["items"][index] = _normalize_item(item)
    payload["events"] = [*payload.get("events", []), _event(item, "archive" if archived else "restore", item.get("title", ""))][-500:]
    save_managed_recurring(payload, user_id=user_id)
    return {"ok": True, "message": f"{item.get('title', 'Item')} {'archived' if archived else 'restored'}."}


def delete_item(item_id: str, user_id: str | None = None) -> dict[str, Any]:
    payload = load_managed_recurring(user_id=user_id)
    index, item = _find_item(payload, item_id)
    if item is None:
        return {"ok": False, "error": "Item not found."}
    rule_id = str(item.get("recurring_rule_id") or "")
    if rule_id:
        delete_pending_for_source("recurring", rule_id, only_pending=True)
        delete_recurring(rule_id)
    payload["items"].pop(index)
    payload["events"] = [*payload.get("events", []), _event(item, "delete", item.get("title", ""))][-500:]
    save_managed_recurring(payload, user_id=user_id)
    return {"ok": True, "message": f"{item.get('title', 'Item')} deleted."}


def mark_checked_from_form(item_id: str, form: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    payload = load_managed_recurring(user_id=user_id)
    index, item = _find_item(payload, item_id)
    if item is None:
        return {"ok": False, "error": "Item not found."}

    check_result = _apply_pending_check_from_form(form)
    if not check_result.get("ok"):
        return check_result

    pending_id = str(check_result.get("pending_id") or "")
    checked_amount = float(check_result.get("checked_amount") or 0.0)
    item.update({
        "last_checked_at": _now(),
        "last_checked_amount": f"{checked_amount:.2f}" if checked_amount > 0 else "",
        "last_checked_pending_id": pending_id,
        "next_due_amount": "",
        "updated_at": _now(),
    })
    payload["items"][index] = _normalize_item(item)
    payload["events"] = [*payload.get("events", []), _event(item, "check", f"Checked pending {pending_id}")][-500:]
    save_managed_recurring(payload, user_id=user_id)
    return {"ok": True, "message": f"{item.get('title', 'Item')} checked at € {checked_amount:.2f}."}


def execute_pending_from_form(form: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    pending_id = str(form.get("pending_id") or "").strip()
    if not pending_id:
        return {"ok": False, "error": "Missing pending id."}

    # The execute button is in the same row as the checked amount. Users expect
    # the edited value to be used immediately, even if they did not first press
    # "Save check". Persist the corrected pending amount/date before execution.
    check_result = _apply_pending_check_from_form(form)
    if not check_result.get("ok"):
        return check_result

    item_id = str(form.get("item_id") or "").strip()
    if item_id:
        _record_item_check_metadata(
            item_id,
            pending_id=pending_id,
            checked_amount=float(check_result.get("checked_amount") or 0.0),
            user_id=user_id,
            event_action="execute_check",
        )

    ok = execute_pending_by_id(
        pending_id,
        execution_date=form.get("execution_date") or date.today().isoformat(),
    )
    if ok and item_id:
        _clear_next_due_amount(item_id, user_id=user_id)
    return {"ok": ok, "message": "Pending payment executed with the checked amount." if ok else "Pending payment was not executed."}


def _apply_pending_check_from_form(form: Mapping[str, Any]) -> dict[str, Any]:
    pending_id = str(form.get("pending_id") or "").strip()
    if not pending_id:
        return {"ok": False, "error": "Missing pending id."}

    # The browser sends this value both for Save check and Execute. Keep comma
    # decimals supported, but reject empty/zero values so an accidental blank
    # cannot silently keep the old generated amount.
    checked_amount = _money(form.get("checked_amount"))
    if checked_amount <= 0:
        return {"ok": False, "error": "Insert a checked amount greater than zero."}

    updates: dict[str, Any] = {"amount": f"{checked_amount:.2f}"}
    checked_due_date = _clean_date(form.get("checked_due_date"))
    if checked_due_date:
        updates["date_due"] = checked_due_date

    update_pending(pending_id, updates)
    return {
        "ok": True,
        "pending_id": pending_id,
        "checked_amount": checked_amount,
        "checked_due_date": checked_due_date,
    }


def _record_item_check_metadata(
    item_id: str,
    *,
    pending_id: str,
    checked_amount: float,
    user_id: str | None = None,
    event_action: str = "check",
) -> None:
    payload = load_managed_recurring(user_id=user_id)
    index, item = _find_item(payload, item_id)
    if item is None:
        return

    item.update({
        "last_checked_at": _now(),
        "last_checked_amount": f"{checked_amount:.2f}" if checked_amount > 0 else "",
        "last_checked_pending_id": pending_id,
        "updated_at": _now(),
    })
    payload["items"][index] = _normalize_item(item)
    payload["events"] = [*payload.get("events", []), _event(item, event_action, f"Checked pending {pending_id} at € {checked_amount:.2f}")][-500:]
    save_managed_recurring(payload, user_id=user_id)


def _clear_next_due_amount(item_id: str, user_id: str | None = None) -> None:
    payload = load_managed_recurring(user_id=user_id)
    index, item = _find_item(payload, item_id)
    if item is None:
        return
    item["next_due_amount"] = ""
    item["updated_at"] = _now()
    payload["items"][index] = _normalize_item(item)
    save_managed_recurring(payload, user_id=user_id)


def _pending_rows_with_next_due_amount(rows: list[dict], next_due_amount: float) -> list[dict]:
    decorated: list[dict] = []
    override_used = False
    for row in rows:
        item = dict(row)
        amount_value = float(item.get("amount_value") or 0.0)
        display_value = amount_value
        if next_due_amount > 0 and not override_used:
            display_value = next_due_amount
            override_used = True
            item["managed_has_next_due_amount"] = True
            item["managed_next_due_amount_label"] = f"Next due override: € {next_due_amount:.2f}"
        else:
            item["managed_has_next_due_amount"] = False
            item["managed_next_due_amount_label"] = ""
        item["managed_checked_amount_value"] = display_value
        item["managed_checked_amount_display"] = f"{display_value:.2f}"
        decorated.append(item)
    return decorated


def load_managed_recurring(user_id: str | None = None) -> dict[str, Any]:
    return _normalize_payload(read_json_secure(_path(user_id), default=None, user_id=user_id))


def save_managed_recurring(payload: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    normalized = _normalize_payload(payload)
    normalized["updated_at"] = _now()
    write_json_secure(_path(user_id), normalized, user_id=user_id)
    return normalized


def _decorate_item(item: Mapping[str, Any], recurring_by_id: dict[str, dict], pending_rows: list[dict], user_id: str | None = None) -> dict[str, Any] | None:
    item = _normalize_item(item)
    rule = recurring_by_id.get(str(item.get("recurring_rule_id") or ""))
    if not rule:
        return None

    try:
        contact = get_contact(item.get("contact_id") or "", user_id=user_id) if item.get("contact_id") else None
    except Exception:
        contact = None

    row_pending = [row for row in pending_rows if row.get("source") == "recurring" and str(row.get("source_id")) == str(rule.get("id"))]
    try:
        pending_prepared = prepare_pending_for_display(row_pending)
    except Exception:
        pending_prepared = {"pending": [], "executed": []}
    pending_open = pending_prepared.get("pending", [])
    pending_executed = pending_prepared.get("executed", [])[:5]

    try:
        next_due = next_due_date_for_rule(rule)
        next_due_display = next_due.isoformat()
    except Exception:
        next_due_display = ""

    amount = normalize_amount(rule.get("amount"))
    due_open = [row for row in pending_open if row.get("is_due_today") or row.get("is_overdue")]
    last_check_label = _short_datetime(item.get("last_checked_at")) or "Never"
    try:
        contact_payload = contact_view(contact, show_sensitive_data=True) if contact else None
    except Exception:
        contact_payload = None

    next_due_amount_value = _optional_money(item.get("next_due_amount"))
    pending_open = _pending_rows_with_next_due_amount(pending_open, next_due_amount_value)

    return {
        **item,
        "rule": rule,
        "rule_id": rule.get("id", ""),
        "contact": contact_payload,
        "contact_name": (contact or {}).get("display_name", ""),
        "type": rule.get("type", ""),
        "category": rule.get("category", ""),
        "amount_value": amount,
        "amount_display": f"{amount:.2f}",
        "next_due_amount_value": next_due_amount_value,
        "next_due_amount_display": f"{next_due_amount_value:.2f}" if next_due_amount_value > 0 else "",
        "has_next_due_amount": next_due_amount_value > 0,
        "frequency": rule.get("frequency", "1"),
        "day_of_month": rule.get("day_of_month", "1"),
        "start_date": rule.get("start_date", ""),
        "end_date": rule.get("end_date", ""),
        "max_occurrences": rule.get("max_occurrences", ""),
        "account_id": rule.get("account_id", ""),
        "payment_method_id": rule.get("payment_method_id", ""),
        "next_due": next_due_display or "Not scheduled",
        "next_due_sort": next_due_display or "9999-99-99",
        "pending_open": pending_open,
        "pending_executed": pending_executed,
        "needs_check": bool(item.get("manual_check_required") and due_open),
        "due_open": due_open,
        "last_check_label": last_check_label,
    }


def _recurring_payload_for_kind(kind: str, form: Mapping[str, Any], *, title: str, amount: float, user_id: str | None = None) -> dict[str, Any]:
    meta = KIND_META[_clean_kind(kind)]
    account_id = form.get("account_id") or form.get("account") or ""
    payment_method_id = form.get("payment_method_id") or ""
    tx_type = meta["type"]
    if tx_type == "income":
        payment_method_id = ""
    account_snapshot = snapshot_account(account_id, user_id=user_id)
    payment_snapshot = snapshot_payment_method(payment_method_id, user_id=user_id)
    return {
        "name": title,
        "type": tx_type,
        "amount": amount,
        "frequency": _positive_int(form.get("frequency"), 1),
        "day_of_month": min(31, max(1, _positive_int(form.get("day_of_month"), 1))),
        "category": _clean_text(form.get("category")) or meta["default_category"],
        "account": form.get("account") or account_id or "auto",
        "account_id": account_snapshot.get("account_id", ""),
        "account_name_snapshot": account_snapshot.get("account_name_snapshot", ""),
        "payment_method_id": payment_snapshot.get("payment_method_id", ""),
        "payment_method_name_snapshot": payment_snapshot.get("payment_method_name_snapshot", ""),
        "payment_resolution_template_json": "",
        "start_date": _clean_date(form.get("start_date")) or date.today().isoformat(),
        "end_date": _clean_date(form.get("end_date")),
        "max_occurrences": str(_positive_int(form.get("max_occurrences"), 0) or ""),
    }


def _normalize_payload(payload: Any) -> dict[str, Any]:
    payload = dict(payload or {}) if isinstance(payload, Mapping) else {}
    items = [_normalize_item(row) for row in payload.get("items", []) if isinstance(row, Mapping)]
    events = [dict(row) for row in payload.get("events", []) if isinstance(row, Mapping)]
    return {
        "schema_version": int(payload.get("schema_version") or 1),
        "items": items,
        "events": events[-500:],
        "updated_at": _clean_text(payload.get("updated_at")),
    }


def _normalize_item(data: Mapping[str, Any]) -> dict[str, Any]:
    kind = _clean_kind(data.get("kind"))
    return {
        "id": _clean_id(data.get("id")) or _new_id("managed"),
        "kind": kind,
        "title": _clean_text(data.get("title") or data.get("name")) or KIND_META[kind]["singular"],
        "contact_id": _clean_id(data.get("contact_id")),
        "recurring_rule_id": _clean_id(data.get("recurring_rule_id")),
        "variable_amount": _truthy(data.get("variable_amount"), default=kind == KIND_BILL),
        "manual_check_required": _truthy(data.get("manual_check_required"), default=True),
        "next_due_amount": _money_text_or_empty(data.get("next_due_amount")),
        "notes": _clean_multiline(data.get("notes")),
        "is_active": _truthy(data.get("is_active"), default=True),
        "last_checked_at": _clean_text(data.get("last_checked_at")),
        "last_checked_amount": _clean_text(data.get("last_checked_amount")),
        "last_checked_pending_id": _clean_text(data.get("last_checked_pending_id")),
        "created_at": _clean_text(data.get("created_at")),
        "updated_at": _clean_text(data.get("updated_at")),
        "archived_at": _clean_text(data.get("archived_at")),
    }


def _find_item(payload: Mapping[str, Any], item_id: str) -> tuple[int, dict[str, Any] | None]:
    wanted = _clean_id(item_id)
    items = list(payload.get("items", []))
    for idx, item in enumerate(items):
        if _clean_id(item.get("id")) == wanted:
            return idx, dict(item)
    return -1, None


def _event(item: Mapping[str, Any], event_type: str, message: str) -> dict[str, Any]:
    return {
        "id": _new_id("event"),
        "item_id": item.get("id", ""),
        "kind": item.get("kind", ""),
        "event_type": event_type,
        "message": message,
        "created_at": _now(),
    }


def _path(user_id: str | None = None):
    return user_data_path(MANAGED_RECURRING_FILENAME, user_id=user_id or get_current_user_id())


def _clean_kind(value: Any) -> str:
    kind = str(value or "").strip().casefold()
    return kind if kind in MANAGED_KINDS else KIND_BILL


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _clean_id(value: Any) -> str:
    text = str(value or "").strip().lower()
    return "".join(ch for ch in text if ch.isalnum() or ch in {"_", "-"})[:80]


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _clean_multiline(value: Any) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [" ".join(line.strip().split()) for line in text.split("\n")]
    return "\n".join(line for line in lines if line).strip()


def _clean_date(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return ""


def _money(value: Any) -> float:
    try:
        return round(max(0.0, float(str(value or 0).replace(",", "."))), 2)
    except (TypeError, ValueError):
        return 0.0


def _optional_money(value: Any) -> float:
    if value is None:
        return 0.0
    text = str(value).strip()
    if not text:
        return 0.0
    return _money(text)


def _money_text_or_empty(value: Any) -> str:
    parsed = _optional_money(value)
    return f"{parsed:.2f}" if parsed > 0 else ""


def _positive_int(value: Any, default: int = 1) -> int:
    try:
        parsed = int(float(str(value or default).replace(",", ".")))
    except (TypeError, ValueError):
        parsed = default
    return max(0, parsed)


def _truthy(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().casefold()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off", ""}:
        return False
    return bool(value)


def _short_datetime(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return text[:16]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
