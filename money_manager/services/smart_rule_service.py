from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from money_manager.config.paths import SMART_RULES_JSON
from money_manager.security.secure_storage import read_json_secure, write_json_secure


BUILTIN_RULES = [
    {
        "id": "builtin_onedrive_subscription",
        "name": "OneDrive subscription",
        "contains": "onedrive",
        "transaction_type": "expense",
        "category": "Subscriptions",
        "sub_category": "OneDrive",
        "linked_object_type": "recurring",
        "enabled": True,
        "builtin": True,
    },
    {
        "id": "builtin_salary_income",
        "name": "Salary income",
        "contains": "salary",
        "transaction_type": "income",
        "category": "Salary",
        "sub_category": "Salary",
        "enabled": True,
        "builtin": True,
    },
    {
        "id": "builtin_bonifico_debt",
        "name": "Bonifico debt hint",
        "contains": "debt payment",
        "transaction_type": "expense",
        "category": "Debt",
        "enabled": True,
        "builtin": True,
    },
]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _payload() -> dict[str, Any]:
    payload = read_json_secure(SMART_RULES_JSON, default=None)
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("schema_version", 1)
    payload.setdefault("rules", [])
    payload.setdefault("events", [])
    payload.setdefault("updated_at", "")
    if not isinstance(payload["rules"], list):
        payload["rules"] = []
    return payload


def _save(payload: Mapping[str, Any]) -> None:
    data = dict(payload)
    data["updated_at"] = _now()
    write_json_secure(SMART_RULES_JSON, data)


def all_rules() -> list[dict[str, Any]]:
    payload = _payload()
    custom = [dict(row) for row in payload.get("rules", []) if isinstance(row, dict)]
    builtin_ids = {str(row.get("id", "")) for row in custom}
    builtins = [dict(row) for row in BUILTIN_RULES if row["id"] not in builtin_ids]
    return [*custom, *builtins]


def add_rule_from_form(form) -> None:
    payload = _payload()
    rules = payload.setdefault("rules", [])
    name = str(form.get("name") or "").strip() or "Smart rule"
    contains = str(form.get("contains") or "").strip()
    if not contains:
        return
    rule_id = f"rule_{int(datetime.now().timestamp())}_{len(rules)+1}"
    rules.append({
        "id": rule_id,
        "name": name,
        "contains": contains,
        "transaction_type": str(form.get("transaction_type") or "").strip().casefold(),
        "category": str(form.get("category") or "").strip(),
        "sub_category": str(form.get("sub_category") or "").strip(),
        "linked_object_type": str(form.get("linked_object_type") or "").strip().casefold(),
        "linked_object_id": str(form.get("linked_object_id") or "").strip(),
        "linked_object_name": str(form.get("linked_object_name") or "").strip(),
        "enabled": bool(form.get("enabled", "1")),
        "builtin": False,
        "created_at": _now(),
    })
    _save(payload)


def delete_rule_from_form(form) -> None:
    rule_id = str(form.get("id") or "").strip()
    if not rule_id:
        return
    payload = _payload()
    payload["rules"] = [row for row in payload.get("rules", []) if str(row.get("id")) != rule_id]
    _save(payload)


def toggle_rule_from_form(form) -> None:
    rule_id = str(form.get("id") or "").strip()
    if not rule_id:
        return
    payload = _payload()
    for row in payload.get("rules", []):
        if str(row.get("id")) == rule_id:
            row["enabled"] = not _truthy(row.get("enabled", True))
            row["updated_at"] = _now()
            break
    else:
        # Built-in rules are copied as disabled/enabled overrides when toggled.
        for row in BUILTIN_RULES:
            if row["id"] == rule_id:
                clone = dict(row)
                clone["enabled"] = not _truthy(row.get("enabled", True))
                clone["created_at"] = _now()
                payload.setdefault("rules", []).append(clone)
                break
    _save(payload)


def automation_context() -> dict[str, Any]:
    rules = all_rules()
    enabled = [row for row in rules if _truthy(row.get("enabled", True))]
    return {"smart_rules": rules, "smart_rules_enabled_count": len(enabled), "smart_rules_total_count": len(rules)}


def apply_smart_rules_to_transaction(tx: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(tx or {})
    text = " ".join(str(result.get(key) or "") for key in ["description", "category", "sub_category", "transfer_reference", "contact_name"]).casefold()
    tx_type = str(result.get("type") or "").strip().casefold()
    if not text:
        return result
    for rule in all_rules():
        if not _truthy(rule.get("enabled", True)):
            continue
        wanted_type = str(rule.get("transaction_type") or "").strip().casefold()
        if wanted_type and tx_type and wanted_type != tx_type:
            continue
        needle = str(rule.get("contains") or "").strip().casefold()
        if not needle or needle not in text:
            continue
        if rule.get("category") and not str(result.get("category") or "").strip():
            result["category"] = rule.get("category")
        if rule.get("sub_category") and not str(result.get("sub_category") or "").strip():
            result["sub_category"] = rule.get("sub_category")
        if rule.get("linked_object_type") and not str(result.get("linked_object_type") or "").strip():
            result["linked_object_type"] = rule.get("linked_object_type")
            result["linked_object_id"] = rule.get("linked_object_id", "")
            result["linked_object_name"] = rule.get("linked_object_name") or rule.get("name") or "Smart linked object"
        break
    return result


def _truthy(value: Any) -> bool:
    return str(value).strip().casefold() in {"1", "true", "yes", "on", "enabled"}
