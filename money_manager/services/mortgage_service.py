from __future__ import annotations

import math
import uuid
from calendar import monthrange
from datetime import date, datetime, timezone
from typing import Any, Mapping

from money_manager.config.user_paths import get_current_user_id, user_data_path
from money_manager.repositories.parent_support import (
    append_rule as append_parent_support_rule,
    delete_rule as delete_parent_support_rule,
    load_rules as load_parent_support_rules,
    update_rule as update_parent_support_rule,
)
from money_manager.repositories.pending import delete_pending_for_source
from money_manager.repositories.recurring import append_recurring, delete_recurring, update_recurring
from money_manager.security.secure_storage import read_json_secure, write_json_secure
from money_manager.services.contact_service import contact_view, get_contact, list_contacts
from money_manager.services.payment_form_service import (
    account_options_for_payment_forms,
    payment_method_options_for_forms,
    snapshot_account,
    snapshot_payment_method,
)

MORTGAGES_FILENAME = "mortgages.json"
PAYER_SELF = "self"
PAYER_PARENT_SUPPORT = "parent_support"
PARENT_SUPPORT_MORTGAGE_CATEGORY = "House mortgage"
PARENT_SUPPORT_DIRECT_PAYMENT = "paid directly by parent"


def mortgages_page_context(*, message: str = "", error: str = "", user_id: str | None = None) -> dict[str, Any]:
    payload = load_mortgages(user_id=user_id)
    parent_support_rules = _parent_support_rule_options()
    parent_support_rules_by_id = {str(rule.get("id", "")): rule for rule in parent_support_rules}
    mortgages = [
        _decorate_mortgage(row, user_id=user_id, parent_support_rules_by_id=parent_support_rules_by_id)
        for row in payload.get("mortgages", [])
    ]
    active = [row for row in mortgages if row.get("is_active")]
    archived = [row for row in mortgages if not row.get("is_active")]
    total_requested = sum(float(row.get("requested_amount") or 0.0) for row in active)
    total_property = sum(float(row.get("property_value") or 0.0) for row in active)
    total_monthly = sum(float(row.get("monthly_payment") or 0.0) for row in active)
    total_parent_paid = sum(float(row.get("monthly_payment") or 0.0) for row in active if row.get("payer_mode") == PAYER_PARENT_SUPPORT)
    companies = [
        contact_view(contact, show_sensitive_data=True)
        for contact in list_contacts(include_archived=False)
        if contact.get("type") == "company"
    ]
    return {
        "message": message,
        "error": error,
        "mortgages": active,
        "archived_mortgages": archived,
        "contacts": companies,
        "parent_support_rules": parent_support_rules,
        "account_options": account_options_for_payment_forms(),
        "payment_method_options": payment_method_options_for_forms(),
        "totals": {
            "active_count": len(active),
            "total_requested": total_requested,
            "total_requested_display": f"{total_requested:.2f}",
            "total_property": total_property,
            "total_property_display": f"{total_property:.2f}",
            "total_monthly": total_monthly,
            "total_monthly_display": f"{total_monthly:.2f}",
            "total_parent_paid": total_parent_paid,
            "total_parent_paid_display": f"{total_parent_paid:.2f}",
        },
    }


def create_mortgage_from_form(form: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    mortgage = _normalize_mortgage(_mortgage_from_form(form))
    if not mortgage["name"]:
        return {"ok": False, "error": "Insert a mortgage/property name."}
    if mortgage["requested_amount"] <= 0:
        return {"ok": False, "error": "Insert the requested loan amount."}
    if mortgage["years"] <= 0:
        return {"ok": False, "error": "Insert the mortgage duration in years."}

    mortgage["id"] = _new_id("mortgage")
    mortgage["created_at"] = _now()
    mortgage["updated_at"] = _now()
    mortgage["monthly_payment"] = _monthly_payment_for(mortgage)

    if mortgage["payer_mode"] == PAYER_PARENT_SUPPORT:
        mortgage["recurring_rule_id"] = ""
        mortgage = _sync_parent_support_rule(mortgage, form, old=None)
    elif _truthy(form.get("create_recurring"), default=True):
        mortgage["recurring_rule_id"] = str(append_recurring(_recurring_payload(mortgage, form, user_id=user_id)) or "")

    payload = load_mortgages(user_id=user_id)
    payload["mortgages"] = [*payload.get("mortgages", []), mortgage]
    payload["events"] = [*payload.get("events", []), _event(mortgage, "create", f"Created {mortgage['name']}")][-500:]
    save_mortgages(payload, user_id=user_id)
    return {"ok": True, "message": f"{mortgage['name']} saved."}


def update_mortgage_from_form(mortgage_id: str, form: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    payload = load_mortgages(user_id=user_id)
    index, old = _find_mortgage(payload, mortgage_id)
    if old is None:
        return {"ok": False, "error": "Mortgage not found."}
    old = _normalize_mortgage(old)
    mortgage = _normalize_mortgage({**old, **_mortgage_from_form(form)})
    if not mortgage["name"]:
        return {"ok": False, "error": "Insert a mortgage/property name."}
    if mortgage["requested_amount"] <= 0:
        return {"ok": False, "error": "Insert the requested loan amount."}
    if mortgage["years"] <= 0:
        return {"ok": False, "error": "Insert the mortgage duration in years."}

    mortgage["monthly_payment"] = _monthly_payment_for(mortgage)
    rule_id = str(old.get("recurring_rule_id") or "")

    if mortgage["payer_mode"] == PAYER_PARENT_SUPPORT:
        if rule_id:
            delete_pending_for_source("recurring", rule_id, only_pending=True)
            delete_recurring(rule_id)
            mortgage["recurring_rule_id"] = ""
        mortgage = _sync_parent_support_rule(mortgage, form, old=old)
    else:
        _delete_managed_parent_support_rule_if_needed(old)
        mortgage["parent_support_rule_id"] = ""
        mortgage["parent_support_managed"] = False
        mortgage["parent_support_parent"] = ""
        if _truthy(form.get("create_recurring"), default=bool(rule_id)):
            if rule_id:
                delete_pending_for_source("recurring", rule_id, only_pending=True)
                update_recurring(rule_id, _recurring_payload(mortgage, form, user_id=user_id))
                mortgage["recurring_rule_id"] = rule_id
            else:
                mortgage["recurring_rule_id"] = str(append_recurring(_recurring_payload(mortgage, form, user_id=user_id)) or "")
        elif rule_id:
            delete_pending_for_source("recurring", rule_id, only_pending=True)
            delete_recurring(rule_id)
            mortgage["recurring_rule_id"] = ""

    mortgage["updated_at"] = _now()
    payload["mortgages"][index] = _normalize_mortgage(mortgage)
    payload["events"] = [*payload.get("events", []), _event(mortgage, "update", f"Updated {mortgage['name']}")][-500:]
    save_mortgages(payload, user_id=user_id)
    return {"ok": True, "message": f"{mortgage['name']} updated."}


def archive_mortgage(mortgage_id: str, *, archived: bool = True, user_id: str | None = None) -> dict[str, Any]:
    payload = load_mortgages(user_id=user_id)
    index, mortgage = _find_mortgage(payload, mortgage_id)
    if mortgage is None:
        return {"ok": False, "error": "Mortgage not found."}
    mortgage = _normalize_mortgage(mortgage)
    mortgage["is_active"] = not archived
    mortgage["archived_at"] = _now() if archived else ""
    mortgage["updated_at"] = _now()
    _set_managed_parent_support_rule_active(mortgage, active=not archived)
    payload["mortgages"][index] = _normalize_mortgage(mortgage)
    payload["events"] = [*payload.get("events", []), _event(mortgage, "archive" if archived else "restore", mortgage.get("name", ""))][-500:]
    save_mortgages(payload, user_id=user_id)
    return {"ok": True, "message": f"{mortgage.get('name', 'Mortgage')} {'archived' if archived else 'restored'}."}


def delete_mortgage(mortgage_id: str, user_id: str | None = None) -> dict[str, Any]:
    payload = load_mortgages(user_id=user_id)
    index, mortgage = _find_mortgage(payload, mortgage_id)
    if mortgage is None:
        return {"ok": False, "error": "Mortgage not found."}
    mortgage = _normalize_mortgage(mortgage)
    rule_id = str(mortgage.get("recurring_rule_id") or "")
    if rule_id:
        delete_pending_for_source("recurring", rule_id, only_pending=True)
        delete_recurring(rule_id)
    _delete_managed_parent_support_rule_if_needed(mortgage)
    payload["mortgages"].pop(index)
    payload["events"] = [*payload.get("events", []), _event(mortgage, "delete", mortgage.get("name", ""))][-500:]
    save_mortgages(payload, user_id=user_id)
    return {"ok": True, "message": f"{mortgage.get('name', 'Mortgage')} deleted."}


def load_mortgages(user_id: str | None = None) -> dict[str, Any]:
    return _normalize_payload(read_json_secure(_path(user_id), default=None, user_id=user_id))


def save_mortgages(payload: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    normalized = _normalize_payload(payload)
    normalized["updated_at"] = _now()
    write_json_secure(_path(user_id), normalized, user_id=user_id)
    return normalized


def _decorate_mortgage(
    row: Mapping[str, Any],
    user_id: str | None = None,
    parent_support_rules_by_id: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    mortgage = _normalize_mortgage(row)
    mortgage["monthly_payment"] = _monthly_payment_for(mortgage)
    projection = _projection(mortgage)
    contact = get_contact(mortgage.get("bank_contact_id") or "", user_id=user_id) if mortgage.get("bank_contact_id") else None
    mortgage["bank_contact"] = contact_view(contact, show_sensitive_data=True) if contact else None
    mortgage["loan_to_value"] = _ratio(mortgage["requested_amount"], mortgage["property_value"])
    mortgage["loan_to_value_display"] = f"{mortgage['loan_to_value']:.1f}%" if mortgage["loan_to_value"] else "—"
    mortgage["down_payment"] = max(0.0, mortgage["property_value"] - mortgage["requested_amount"])
    mortgage["down_payment_display"] = f"{mortgage['down_payment']:.2f}"
    mortgage["monthly_payment_display"] = f"{mortgage['monthly_payment']:.2f}"
    mortgage["total_interest_display"] = f"{projection['total_interest']:.2f}"
    mortgage["total_paid_display"] = f"{projection['total_paid']:.2f}"
    mortgage["payer_label"] = "Parent support pays directly" if mortgage["payer_mode"] == PAYER_PARENT_SUPPORT else "Paid from my account"
    mortgage["payer_badge"] = "Parent support" if mortgage["payer_mode"] == PAYER_PARENT_SUPPORT else "Own account"
    rules_by_id = parent_support_rules_by_id or {}
    linked_rule = rules_by_id.get(str(mortgage.get("parent_support_rule_id") or ""))
    mortgage["parent_support_rule"] = linked_rule or None
    mortgage["projection"] = projection
    return mortgage


def _mortgage_from_form(form: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "name": _clean_text(form.get("name")),
        "property_address": _clean_text(form.get("property_address")),
        "property_value": _money(form.get("property_value")),
        "requested_amount": _money(form.get("requested_amount")),
        "own_funds": _money(form.get("own_funds")),
        "rate_type": _rate_type(form.get("rate_type")),
        "annual_rate": _float_value(form.get("annual_rate")),
        "euribor_estimate": _float_value(form.get("euribor_estimate")),
        "spread": _float_value(form.get("spread")),
        "years": _positive_int(form.get("years"), 25),
        "start_date": _clean_date(form.get("start_date")) or date.today().isoformat(),
        "payment_day": min(31, max(1, _positive_int(form.get("payment_day"), 1))),
        "manual_monthly_payment": _money(form.get("manual_monthly_payment")),
        "bank_contact_id": _clean_id(form.get("bank_contact_id")),
        "account_id": _clean_id(form.get("account_id")),
        "payment_method_id": _clean_id(form.get("payment_method_id")),
        "category": _clean_text(form.get("category")) or "Mutuo",
        "payer_mode": _payer_mode(form.get("payer_mode")),
        "parent_support_rule_id": _clean_id(form.get("parent_support_rule_id")),
        "parent_support_parent": _clean_text(form.get("parent_support_parent")),
        "notes": _clean_multiline(form.get("notes")),
        "is_active": _truthy(form.get("is_active"), default=True),
    }


def _normalize_payload(payload: Any) -> dict[str, Any]:
    payload = dict(payload or {}) if isinstance(payload, Mapping) else {}
    mortgages = [_normalize_mortgage(row) for row in payload.get("mortgages", []) if isinstance(row, Mapping)]
    events = [dict(row) for row in payload.get("events", []) if isinstance(row, Mapping)]
    return {"schema_version": int(payload.get("schema_version") or 2), "mortgages": mortgages, "events": events[-500:], "updated_at": _clean_text(payload.get("updated_at"))}


def _normalize_mortgage(data: Mapping[str, Any]) -> dict[str, Any]:
    row = dict(data or {})
    annual_rate = _float_value(row.get("annual_rate"))
    return {
        "id": _clean_id(row.get("id")) or _new_id("mortgage"),
        "name": _clean_text(row.get("name")),
        "property_address": _clean_text(row.get("property_address")),
        "property_value": _money(row.get("property_value")),
        "requested_amount": _money(row.get("requested_amount")),
        "own_funds": _money(row.get("own_funds")),
        "rate_type": _rate_type(row.get("rate_type")),
        "annual_rate": annual_rate,
        "euribor_estimate": _float_value(row.get("euribor_estimate")),
        "spread": _float_value(row.get("spread")),
        "years": _positive_int(row.get("years"), 25),
        "start_date": _clean_date(row.get("start_date")) or date.today().isoformat(),
        "payment_day": min(31, max(1, _positive_int(row.get("payment_day"), 1))),
        "manual_monthly_payment": _money(row.get("manual_monthly_payment")),
        "monthly_payment": _money(row.get("monthly_payment")),
        "bank_contact_id": _clean_id(row.get("bank_contact_id")),
        "account_id": _clean_id(row.get("account_id")),
        "payment_method_id": _clean_id(row.get("payment_method_id")),
        "category": _clean_text(row.get("category")) or "Mutuo",
        "payer_mode": _payer_mode(row.get("payer_mode")),
        "parent_support_rule_id": _clean_id(row.get("parent_support_rule_id")),
        "parent_support_parent": _clean_text(row.get("parent_support_parent")),
        "parent_support_managed": _truthy(row.get("parent_support_managed"), default=False),
        "recurring_rule_id": _clean_id(row.get("recurring_rule_id")),
        "notes": _clean_multiline(row.get("notes")),
        "is_active": _truthy(row.get("is_active"), default=True),
        "created_at": _clean_text(row.get("created_at")),
        "updated_at": _clean_text(row.get("updated_at")),
        "archived_at": _clean_text(row.get("archived_at")),
    }


def _monthly_payment_for(mortgage: Mapping[str, Any]) -> float:
    manual = _money(mortgage.get("manual_monthly_payment"))
    if manual > 0:
        return manual
    principal = _money(mortgage.get("requested_amount"))
    months = max(1, _positive_int(mortgage.get("years"), 25) * 12)
    annual_rate = _effective_annual_rate(mortgage) / 100.0
    monthly_rate = annual_rate / 12.0
    if principal <= 0:
        return 0.0
    if abs(monthly_rate) < 0.0000001:
        return round(principal / months, 2)
    payment = principal * (monthly_rate * (1 + monthly_rate) ** months) / ((1 + monthly_rate) ** months - 1)
    return round(payment, 2)


def _effective_annual_rate(mortgage: Mapping[str, Any]) -> float:
    if _rate_type(mortgage.get("rate_type")) == "variable":
        candidate = _float_value(mortgage.get("euribor_estimate")) + _float_value(mortgage.get("spread"))
        return candidate if candidate > 0 else _float_value(mortgage.get("annual_rate"))
    return _float_value(mortgage.get("annual_rate"))


def _projection(mortgage: Mapping[str, Any]) -> dict[str, Any]:
    principal = _money(mortgage.get("requested_amount"))
    months = max(1, _positive_int(mortgage.get("years"), 25) * 12)
    annual_rate = _effective_annual_rate(mortgage) / 100.0
    monthly_rate = annual_rate / 12.0
    payment = _monthly_payment_for(mortgage)
    start = _date_from_iso(mortgage.get("start_date")) or date.today()
    payment_day = min(31, max(1, _positive_int(mortgage.get("payment_day"), 1)))
    paid_count = _paid_installment_count(start, payment_day, months, date.today())

    balance = principal
    total_interest = 0.0
    total_principal_paid = 0.0
    monthly_rows = []
    yearly = []
    timeline = [{
        "month": 0,
        "due_date": start.isoformat(),
        "cumulative_paid": 0.0,
        "cumulative_principal": 0.0,
        "cumulative_interest": 0.0,
        "remaining_balance": principal,
    }]
    paid_principal_year = 0.0
    paid_interest_year = 0.0

    for month in range(1, months + 1):
        interest = round(balance * monthly_rate, 2)
        principal_paid = min(balance, max(0.0, payment - interest))
        if principal_paid <= 0 and payment > 0 and interest <= 0:
            principal_paid = min(balance, payment)
        principal_paid = round(principal_paid, 2)
        balance = max(0.0, round(balance - principal_paid, 2))
        total_interest = round(total_interest + interest, 2)
        total_principal_paid = round(total_principal_paid + principal_paid, 2)
        paid_principal_year = round(paid_principal_year + principal_paid, 2)
        paid_interest_year = round(paid_interest_year + interest, 2)
        due_date = _scheduled_payment_date(start, payment_day, month - 1)
        cumulative_paid = round(total_principal_paid + total_interest, 2)

        if month <= 24:
            monthly_rows.append({
                "month": month,
                "due_date": due_date.isoformat(),
                "payment": payment,
                "payment_display": f"{payment:.2f}",
                "principal": principal_paid,
                "principal_display": f"{principal_paid:.2f}",
                "interest": interest,
                "interest_display": f"{interest:.2f}",
                "balance": balance,
                "balance_display": f"{balance:.2f}",
            })
        timeline.append({
            "month": month,
            "due_date": due_date.isoformat(),
            "cumulative_paid": cumulative_paid,
            "cumulative_principal": total_principal_paid,
            "cumulative_interest": total_interest,
            "remaining_balance": balance,
        })
        if month % 12 == 0 or month == months or balance <= 0:
            yearly.append({
                "year": math.ceil(month / 12),
                "principal_paid": paid_principal_year,
                "principal_paid_display": f"{paid_principal_year:.2f}",
                "interest_paid": paid_interest_year,
                "interest_paid_display": f"{paid_interest_year:.2f}",
                "remaining_balance": balance,
                "remaining_balance_display": f"{balance:.2f}",
            })
            paid_principal_year = 0.0
            paid_interest_year = 0.0
        if balance <= 0:
            break

    paid_count = min(paid_count, len(timeline) - 1)
    current_point = timeline[paid_count] if timeline else {}
    total_paid = round(total_principal_paid + total_interest, 2)
    own_funds = _money(mortgage.get("own_funds"))
    property_value = _money(mortgage.get("property_value"))
    all_in_cost = round(own_funds + total_paid, 2)
    extra_over_property = round(max(0.0, all_in_cost - property_value), 2) if property_value > 0 else round(total_interest, 2)
    payoff_date = timeline[-1].get("due_date", "") if timeline else ""
    progress_percent = (paid_count / max(1, len(timeline) - 1)) * 100.0
    remaining_after_term = float(timeline[-1].get("remaining_balance", 0.0)) if timeline else 0.0

    return {
        "monthly_rows": monthly_rows,
        "yearly_rows": yearly,
        "timeline": timeline,
        "chart": _projection_chart(timeline, paid_count, total_paid=max(total_paid, 1.0), principal=max(principal, 1.0)),
        "payments_done": paid_count,
        "payments_remaining": max(0, (len(timeline) - 1) - paid_count),
        "progress_percent": round(progress_percent, 1),
        "progress_percent_display": f"{progress_percent:.1f}%",
        "paid_to_date": round(float(current_point.get("cumulative_paid", 0.0)), 2),
        "paid_to_date_display": f"{float(current_point.get('cumulative_paid', 0.0)):.2f}",
        "principal_paid_to_date": round(float(current_point.get("cumulative_principal", 0.0)), 2),
        "principal_paid_to_date_display": f"{float(current_point.get('cumulative_principal', 0.0)):.2f}",
        "interest_paid_to_date": round(float(current_point.get("cumulative_interest", 0.0)), 2),
        "interest_paid_to_date_display": f"{float(current_point.get('cumulative_interest', 0.0)):.2f}",
        "remaining_balance_today": round(float(current_point.get("remaining_balance", principal)), 2),
        "remaining_balance_today_display": f"{float(current_point.get('remaining_balance', principal)):.2f}",
        "payoff_date": payoff_date,
        "remaining_after_term": remaining_after_term,
        "remaining_after_term_display": f"{remaining_after_term:.2f}",
        "total_interest": round(total_interest, 2),
        "total_interest_display": f"{total_interest:.2f}",
        "total_paid": round(total_paid, 2),
        "total_paid_display": f"{total_paid:.2f}",
        "all_in_cost": all_in_cost,
        "all_in_cost_display": f"{all_in_cost:.2f}",
        "extra_over_property_value": extra_over_property,
        "extra_over_property_value_display": f"{extra_over_property:.2f}",
        "interest_ratio": _ratio(total_interest, principal),
        "interest_ratio_display": f"{_ratio(total_interest, principal):.1f}%",
        "effective_annual_rate": round(_effective_annual_rate(mortgage), 4),
        "effective_annual_rate_display": f"{_effective_annual_rate(mortgage):.3f}%",
    }


def _projection_chart(timeline: list[dict[str, Any]], paid_count: int, *, total_paid: float, principal: float) -> dict[str, str]:
    if not timeline:
        return {
            "paid_elapsed_points": "",
            "paid_future_points": "",
            "balance_elapsed_points": "",
            "balance_future_points": "",
        }
    max_month = max(1, int(timeline[-1].get("month") or 1))
    split = min(max(0, paid_count), len(timeline) - 1)
    elapsed_points = timeline[: split + 1]
    future_points = timeline[split:]
    return {
        "paid_elapsed_points": _svg_polyline(elapsed_points, "cumulative_paid", max_month=max_month, max_value=total_paid),
        "paid_future_points": _svg_polyline(future_points, "cumulative_paid", max_month=max_month, max_value=total_paid),
        "balance_elapsed_points": _svg_polyline(elapsed_points, "remaining_balance", max_month=max_month, max_value=principal),
        "balance_future_points": _svg_polyline(future_points, "remaining_balance", max_month=max_month, max_value=principal),
    }


def _svg_polyline(points: list[dict[str, Any]], value_key: str, *, max_month: int, max_value: float) -> str:
    if not points:
        return ""
    top = 6.0
    bottom = 54.0
    height = bottom - top
    safe_max = max(max_value, 1.0)
    coords = []
    for point in points:
        month = max(0, int(point.get("month") or 0))
        value = max(0.0, float(point.get(value_key) or 0.0))
        x = (month / max_month) * 100.0 if max_month else 0.0
        y = bottom - min(1.0, value / safe_max) * height
        coords.append(f"{x:.2f},{y:.2f}")
    return " ".join(coords)


def _recurring_payload(mortgage: Mapping[str, Any], form: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    account_id = mortgage.get("account_id") or form.get("account_id") or ""
    payment_method_id = mortgage.get("payment_method_id") or form.get("payment_method_id") or ""
    account_snapshot = snapshot_account(account_id, user_id=user_id)
    payment_snapshot = snapshot_payment_method(payment_method_id, user_id=user_id)
    return {
        "name": f"Mutuo - {mortgage.get('name', '')}".strip(" -"),
        "type": "expense",
        "amount": _monthly_payment_for(mortgage),
        "frequency": 1,
        "day_of_month": mortgage.get("payment_day", 1),
        "category": mortgage.get("category") or "Mutuo",
        "account": form.get("account") or account_id or "auto",
        "account_id": account_snapshot.get("account_id", ""),
        "account_name_snapshot": account_snapshot.get("account_name_snapshot", ""),
        "payment_method_id": payment_snapshot.get("payment_method_id", ""),
        "payment_method_name_snapshot": payment_snapshot.get("payment_method_name_snapshot", ""),
        "payment_resolution_template_json": "",
        "start_date": mortgage.get("start_date") or date.today().isoformat(),
        "end_date": "",
        "max_occurrences": str(max(1, _positive_int(mortgage.get("years"), 25) * 12)),
    }


def _sync_parent_support_rule(mortgage: dict[str, Any], form: Mapping[str, Any], old: Mapping[str, Any] | None = None) -> dict[str, Any]:
    old = _normalize_mortgage(old or {}) if old else {}
    selected_rule_id = _clean_id(form.get("parent_support_rule_id"))
    old_rule_id = _clean_id(old.get("parent_support_rule_id")) if old else ""
    old_managed = _truthy(old.get("parent_support_managed"), default=False) if old else False
    if selected_rule_id:
        rule_id = selected_rule_id
        managed = bool(old_managed and selected_rule_id == old_rule_id)
    elif old_rule_id and old_managed:
        rule_id = old_rule_id
        managed = True
    else:
        rule_id = ""
        managed = True

    parent = _clean_text(form.get("parent_support_parent")) or _clean_text(mortgage.get("parent_support_parent")) or "Parents"
    mortgage["parent_support_parent"] = parent
    payload = _parent_support_rule_payload(mortgage, parent=parent)
    if rule_id:
        _update_parent_support_rule_safe(rule_id, payload)
        mortgage["parent_support_rule_id"] = rule_id
        mortgage["parent_support_managed"] = managed
    else:
        new_id = append_parent_support_rule(payload)
        mortgage["parent_support_rule_id"] = str(new_id or "")
        mortgage["parent_support_managed"] = True
    return mortgage


def _parent_support_rule_payload(mortgage: Mapping[str, Any], *, parent: str) -> dict[str, Any]:
    start = _date_from_iso(mortgage.get("start_date")) or date.today()
    months = max(1, _positive_int(mortgage.get("years"), 25) * 12)
    last_payment = _scheduled_payment_date(start, int(mortgage.get("payment_day") or 1), months - 1)
    return {
        "name": f"Mutuo - {mortgage.get('name', '')}".strip(" -"),
        "kind": "covered_expense",
        "parent": parent,
        "category": PARENT_SUPPORT_MORTGAGE_CATEGORY,
        "monthly_amount": _monthly_payment_for(mortgage),
        "day_of_month": max(1, min(31, int(mortgage.get("payment_day") or 1))),
        "start_date": start.isoformat(),
        "end_date": last_payment.isoformat(),
        "payment_method": PARENT_SUPPORT_DIRECT_PAYMENT,
        "account_id": "",
        "account_name_snapshot": "",
        "payment_method_id": "",
        "payment_method_name_snapshot": "",
        "description": f"Mortgage paid directly through Parent Support. Linked mortgage: {mortgage.get('name', '')} ({mortgage.get('id', '')}).".strip(),
        "active": "yes" if _truthy(mortgage.get("is_active"), default=True) else "no",
    }


def _parent_support_rule_options() -> list[dict[str, Any]]:
    options = []
    for rule in load_parent_support_rules():
        rule_id = str(rule.get("id", "")).strip()
        if not rule_id:
            continue
        amount = _money(rule.get("monthly_amount"))
        name = _clean_text(rule.get("name")) or _clean_text(rule.get("description")) or "Parent support rule"
        parent = _clean_text(rule.get("parent")) or "Parents"
        category = _clean_text(rule.get("category")) or "Other"
        active = _truthy(rule.get("active"), default=True)
        mortgage_related = _looks_like_mortgage_support_rule(rule)
        options.append({
            "id": rule_id,
            "name": name,
            "parent": parent,
            "category": category,
            "amount": amount,
            "amount_display": f"{amount:.2f}",
            "active": active,
            "mortgage_related": mortgage_related,
            "label": f"{name} · {parent} · € {amount:.2f}/mo" + ("" if active else " · inactive"),
        })
    return sorted(options, key=lambda row: (not row["mortgage_related"], not row["active"], row["name"].casefold()))


def _looks_like_mortgage_support_rule(rule: Mapping[str, Any]) -> bool:
    haystack = " ".join(
        str(rule.get(key, "")) for key in ["name", "category", "description", "payment_method"]
    ).casefold()
    return any(token in haystack for token in ["mortgage", "mutuo", "casa", "house mortgage"])


def _update_parent_support_rule_safe(rule_id: str, updates: Mapping[str, Any]) -> None:
    numeric_id = _int_or_none(rule_id)
    if numeric_id is None:
        return
    update_parent_support_rule(numeric_id, dict(updates))


def _delete_managed_parent_support_rule_if_needed(mortgage: Mapping[str, Any]) -> None:
    if not _truthy(mortgage.get("parent_support_managed"), default=False):
        return
    numeric_id = _int_or_none(mortgage.get("parent_support_rule_id"))
    if numeric_id is None:
        return
    delete_parent_support_rule(numeric_id)


def _set_managed_parent_support_rule_active(mortgage: Mapping[str, Any], *, active: bool) -> None:
    if not _truthy(mortgage.get("parent_support_managed"), default=False):
        return
    numeric_id = _int_or_none(mortgage.get("parent_support_rule_id"))
    if numeric_id is None:
        return
    update_parent_support_rule(numeric_id, {"active": "yes" if active else "no"})


def _find_mortgage(payload: Mapping[str, Any], mortgage_id: str) -> tuple[int, dict[str, Any] | None]:
    wanted = _clean_id(mortgage_id)
    rows = list(payload.get("mortgages", []))
    for index, row in enumerate(rows):
        if _clean_id(row.get("id")) == wanted:
            return index, dict(row)
    return -1, None


def _event(mortgage: Mapping[str, Any], event_type: str, message: str) -> dict[str, Any]:
    return {"id": _new_id("event"), "mortgage_id": mortgage.get("id", ""), "event_type": event_type, "message": message, "created_at": _now()}


def _path(user_id: str | None = None):
    return user_data_path(MORTGAGES_FILENAME, user_id=user_id or get_current_user_id())


def _payer_mode(value: Any) -> str:
    text = str(value or PAYER_SELF).strip().casefold().replace("-", "_")
    if text in {PAYER_PARENT_SUPPORT, "parent", "parents", "parental_support", "paid_by_parent"}:
        return PAYER_PARENT_SUPPORT
    return PAYER_SELF


def _rate_type(value: Any) -> str:
    text = str(value or "fixed").strip().casefold()
    return text if text in {"fixed", "variable"} else "fixed"


def _ratio(numerator: float, denominator: float) -> float:
    return round((numerator / denominator) * 100.0, 2) if denominator else 0.0


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


def _date_from_iso(value: Any) -> date | None:
    text = _clean_date(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _scheduled_payment_date(start: date, payment_day: int, month_offset: int) -> date:
    day = max(1, int(payment_day or 1))
    first_day = min(day, monthrange(start.year, start.month)[1])
    first_candidate = date(start.year, start.month, first_day)
    first_month_shift = 1 if first_candidate < start else 0
    total_month = (start.month - 1) + max(0, int(month_offset)) + first_month_shift
    year = start.year + total_month // 12
    month = (total_month % 12) + 1
    due_day = min(day, monthrange(year, month)[1])
    return date(year, month, due_day)


def _paid_installment_count(start: date, payment_day: int, months: int, today_value: date) -> int:
    count = 0
    seen_dates: set[date] = set()
    offset = 0
    while count < months and offset < months + 2:
        due = _scheduled_payment_date(start, payment_day, offset)
        offset += 1
        if due in seen_dates:
            continue
        seen_dates.add(due)
        if due <= today_value:
            count += 1
            continue
        break
    return min(count, months)


def _money(value: Any) -> float:
    try:
        return round(max(0.0, float(str(value or 0).replace(",", "."))), 2)
    except (TypeError, ValueError):
        return 0.0


def _float_value(value: Any) -> float:
    try:
        return float(str(value or 0).replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def _positive_int(value: Any, default: int = 1) -> int:
    try:
        return max(0, int(float(str(value or default).replace(",", "."))))
    except (TypeError, ValueError):
        return default


def _int_or_none(value: Any) -> int | None:
    try:
        return int(str(value or "").strip())
    except (TypeError, ValueError):
        return None


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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
