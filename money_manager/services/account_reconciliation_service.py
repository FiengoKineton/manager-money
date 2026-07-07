from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from money_manager.config.paths import ACCOUNT_RECONCILIATION_JSON
from money_manager.security.secure_storage import read_json_secure, write_json_secure
from money_manager.services.account_scope_service import all_financial_center_summaries, scope_balance_summary


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _payload() -> dict[str, Any]:
    payload = read_json_secure(ACCOUNT_RECONCILIATION_JSON, default=None)
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("schema_version", 1)
    payload.setdefault("accounts", {})
    payload.setdefault("events", [])
    payload.setdefault("updated_at", "")
    if not isinstance(payload["accounts"], dict):
        payload["accounts"] = {}
    if not isinstance(payload["events"], list):
        payload["events"] = []
    return payload


def _save(payload: Mapping[str, Any]) -> None:
    data = dict(payload)
    data["updated_at"] = _now()
    write_json_secure(ACCOUNT_RECONCILIATION_JSON, data)


def update_reconciliation_from_form(form) -> None:
    account_id = str(form.get("account_id") or "").strip()
    if not account_id:
        return
    real_balance = _amount(form.get("real_balance"))
    note = str(form.get("note") or "").strip()
    payload = _payload()
    previous = payload["accounts"].get(account_id, {})
    record = {
        "account_id": account_id,
        "real_balance": f"{real_balance:.2f}",
        "note": note,
        "checked_at": _now(),
    }
    payload["accounts"][account_id] = record
    payload["events"].append({
        "account_id": account_id,
        "real_balance": f"{real_balance:.2f}",
        "previous_real_balance": previous.get("real_balance", ""),
        "note": note,
        "created_at": record["checked_at"],
    })
    if len(payload["events"]) > 1000:
        payload["events"] = payload["events"][-1000:]
    _save(payload)


def reconciliation_context() -> dict[str, Any]:
    payload = _payload()
    checkpoints = payload.get("accounts", {}) if isinstance(payload.get("accounts"), dict) else {}
    rows = []
    for summary in all_financial_center_summaries():
        account_id = str(summary.get("account_id") or summary.get("key") or "")
        checkpoint = checkpoints.get(account_id, {}) if account_id else {}
        app_balance = float(summary.get("net_balance", 0.0) or 0.0)
        real_balance = _optional_amount(checkpoint.get("real_balance"))
        difference = None if real_balance is None else round(real_balance - app_balance, 2)
        rows.append({
            "account_id": account_id,
            "label": summary.get("label") or account_id,
            "app_balance": app_balance,
            "real_balance": real_balance,
            "difference": difference,
            "note": checkpoint.get("note", ""),
            "checked_at": checkpoint.get("checked_at", ""),
            "status": _status(difference),
            "suggestion": _suggestion(difference),
        })
    rows.sort(key=lambda row: (row["status"] != "Mismatch", abs(row["difference"] or 0)), reverse=True)
    return {"reconciliation_rows": rows, "reconciliation_events": list(reversed(payload.get("events", [])))[0:20]}


def account_reconciliation_summary(account_id: str) -> dict[str, Any]:
    if not account_id:
        return {}
    payload = _payload()
    checkpoint = payload.get("accounts", {}).get(account_id, {}) if isinstance(payload.get("accounts"), dict) else {}
    if not checkpoint:
        return {"has_checkpoint": False}
    try:
        summary = scope_balance_summary(f"account:{account_id}")
        app_balance = float(summary.get("net_balance", 0.0) or 0.0)
    except Exception:
        app_balance = 0.0
    real_balance = _optional_amount(checkpoint.get("real_balance"))
    difference = None if real_balance is None else round(real_balance - app_balance, 2)
    return {
        "has_checkpoint": True,
        "real_balance": real_balance,
        "app_balance": app_balance,
        "difference": difference,
        "checked_at": checkpoint.get("checked_at", ""),
        "note": checkpoint.get("note", ""),
        "status": _status(difference),
        "suggestion": _suggestion(difference),
    }


def _status(difference: float | None) -> str:
    if difference is None:
        return "Not checked"
    if abs(difference) <= 0.01:
        return "Balanced"
    return "Mismatch"


def _suggestion(difference: float | None) -> str:
    if difference is None:
        return "Enter the real bank/app balance to compare it with Money Manager."
    if abs(difference) <= 0.01:
        return "This account matches the real balance."
    if difference > 0:
        return "The real balance is higher. Look for missing income, refund, transfer or starting balance."
    return "The real balance is lower. Look for missing expenses, fees, card payments or duplicated income."


def _optional_amount(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    return _amount(text)


def _amount(value: Any) -> float:
    try:
        return float(str(value or 0).replace(",", "."))
    except (TypeError, ValueError):
        return 0.0
