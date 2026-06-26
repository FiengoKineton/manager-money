from __future__ import annotations

import math
import uuid
from datetime import date, datetime, timezone
from typing import Any, Mapping

from money_manager.config.user_paths import get_current_user_id, user_data_path
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


def mortgages_page_context(*, message: str = "", error: str = "", user_id: str | None = None) -> dict[str, Any]:
    payload = load_mortgages(user_id=user_id)
    mortgages = [_decorate_mortgage(row, user_id=user_id) for row in payload.get("mortgages", [])]
    active = [row for row in mortgages if row.get("is_active")]
    archived = [row for row in mortgages if not row.get("is_active")]
    total_requested = sum(float(row.get("requested_amount") or 0.0) for row in active)
    total_property = sum(float(row.get("property_value") or 0.0) for row in active)
    total_monthly = sum(float(row.get("monthly_payment") or 0.0) for row in active)
    companies = [contact_view(contact, show_sensitive_data=True) for contact in list_contacts(include_archived=False) if contact.get("type") == "company"]
    return {
        "message": message,
        "error": error,
        "mortgages": active,
        "archived_mortgages": archived,
        "contacts": companies,
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

    if _truthy(form.get("create_recurring"), default=True):
        mortgage["monthly_payment"] = _monthly_payment_for(mortgage)
        mortgage["recurring_rule_id"] = str(append_recurring(_recurring_payload(mortgage, form, user_id=user_id)) or "")
    mortgage["id"] = _new_id("mortgage")
    mortgage["created_at"] = _now()
    mortgage["updated_at"] = _now()

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
    mortgage = _normalize_mortgage({**old, **_mortgage_from_form(form)})
    if not mortgage["name"]:
        return {"ok": False, "error": "Insert a mortgage/property name."}
    if mortgage["requested_amount"] <= 0:
        return {"ok": False, "error": "Insert the requested loan amount."}
    if mortgage["years"] <= 0:
        return {"ok": False, "error": "Insert the mortgage duration in years."}

    mortgage["monthly_payment"] = _monthly_payment_for(mortgage)
    rule_id = str(mortgage.get("recurring_rule_id") or "")
    if _truthy(form.get("create_recurring"), default=bool(rule_id)):
        if rule_id:
            delete_pending_for_source("recurring", rule_id, only_pending=True)
            update_recurring(rule_id, _recurring_payload(mortgage, form, user_id=user_id))
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
    mortgage["is_active"] = not archived
    mortgage["archived_at"] = _now() if archived else ""
    mortgage["updated_at"] = _now()
    payload["mortgages"][index] = _normalize_mortgage(mortgage)
    payload["events"] = [*payload.get("events", []), _event(mortgage, "archive" if archived else "restore", mortgage.get("name", ""))][-500:]
    save_mortgages(payload, user_id=user_id)
    return {"ok": True, "message": f"{mortgage.get('name', 'Mortgage')} {'archived' if archived else 'restored'}."}


def delete_mortgage(mortgage_id: str, user_id: str | None = None) -> dict[str, Any]:
    payload = load_mortgages(user_id=user_id)
    index, mortgage = _find_mortgage(payload, mortgage_id)
    if mortgage is None:
        return {"ok": False, "error": "Mortgage not found."}
    rule_id = str(mortgage.get("recurring_rule_id") or "")
    if rule_id:
        delete_pending_for_source("recurring", rule_id, only_pending=True)
        delete_recurring(rule_id)
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


def _decorate_mortgage(row: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
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
        "notes": _clean_multiline(form.get("notes")),
        "is_active": _truthy(form.get("is_active"), default=True),
    }


def _normalize_payload(payload: Any) -> dict[str, Any]:
    payload = dict(payload or {}) if isinstance(payload, Mapping) else {}
    mortgages = [_normalize_mortgage(row) for row in payload.get("mortgages", []) if isinstance(row, Mapping)]
    events = [dict(row) for row in payload.get("events", []) if isinstance(row, Mapping)]
    return {"schema_version": int(payload.get("schema_version") or 1), "mortgages": mortgages, "events": events[-500:], "updated_at": _clean_text(payload.get("updated_at"))}


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
    balance = principal
    total_interest = 0.0
    rows = []
    yearly = []
    paid_principal_year = 0.0
    paid_interest_year = 0.0

    for month in range(1, months + 1):
        interest = round(balance * monthly_rate, 2)
        principal_paid = min(balance, max(0.0, payment - interest))
        if principal_paid <= 0 and payment > 0:
            principal_paid = min(balance, payment)
        balance = max(0.0, round(balance - principal_paid, 2))
        total_interest += interest
        paid_principal_year += principal_paid
        paid_interest_year += interest
        if month <= 24:
            rows.append({
                "month": month,
                "payment": payment,
                "payment_display": f"{payment:.2f}",
                "principal": principal_paid,
                "principal_display": f"{principal_paid:.2f}",
                "interest": interest,
                "interest_display": f"{interest:.2f}",
                "balance": balance,
                "balance_display": f"{balance:.2f}",
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

    total_paid = principal + total_interest
    return {
        "monthly_rows": rows,
        "yearly_rows": yearly,
        "total_interest": round(total_interest, 2),
        "total_paid": round(total_paid, 2),
        "effective_annual_rate": round(_effective_annual_rate(mortgage), 4),
        "effective_annual_rate_display": f"{_effective_annual_rate(mortgage):.3f}%",
    }


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
