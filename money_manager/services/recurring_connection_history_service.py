from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from money_manager.config.user_paths import get_user_data_dir
from money_manager.security.secure_storage import read_json_secure, write_json_secure

_HISTORY_FILE = "recurring_connection_history.json"


def _path() -> Path:
    return get_user_data_dir() / _HISTORY_FILE


def _load() -> dict[str, dict[str, Any]]:
    payload = read_json_secure(_path(), default={})
    return payload if isinstance(payload, dict) else {}


def _write(payload: dict[str, dict[str, Any]]) -> None:
    write_json_secure(_path(), payload)


def remember_rule_connection(rule: Mapping[str, Any] | None) -> None:
    if not rule:
        return
    rule_id = str(rule.get("id") or "").strip()
    if not rule_id:
        return
    connection_type = str(rule.get("connection_type") or "").strip().casefold()
    payload = _load()
    entry = dict(payload.get(rule_id, {}) or {})
    entry.update({
        "rule_id": rule_id,
        "name": str(rule.get("name") or entry.get("name") or f"Rule {rule_id}"),
        "type": str(rule.get("type") or entry.get("type") or "expense"),
        "amount": rule.get("amount", entry.get("amount", 0)),
        "frequency": rule.get("frequency", entry.get("frequency", 1)),
        "connection_contact_id": str(rule.get("connection_contact_id") or entry.get("connection_contact_id") or ""),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    if connection_type == "bonifico":
        entry["ever_bonifico"] = True
        entry["last_bonifico_at"] = entry["updated_at"]
    entry["current_connection_type"] = connection_type
    payload[rule_id] = entry
    _write(payload)


def bonifico_rule_history(current_rules: list[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    payload = _load()
    current_by_id = {str(row.get("id") or ""): dict(row) for row in current_rules}

    # Ensure currently connected rules exist in the history store. The key is
    # the stable rule ID, so toggling a rule never creates duplicate entries.
    changed = False
    for rule_id, row in current_by_id.items():
        if str(row.get("connection_type") or "").casefold() != "bonifico":
            continue
        entry = dict(payload.get(rule_id, {}) or {})
        if not entry.get("ever_bonifico") or entry.get("name") != row.get("name"):
            entry.update({
                "rule_id": rule_id,
                "name": str(row.get("name") or f"Rule {rule_id}"),
                "type": str(row.get("type") or "expense"),
                "amount": row.get("amount", 0),
                "frequency": row.get("frequency", 1),
                "connection_contact_id": str(row.get("connection_contact_id") or ""),
                "ever_bonifico": True,
                "current_connection_type": "bonifico",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            payload[rule_id] = entry
            changed = True
    if changed:
        _write(payload)

    active: list[dict[str, Any]] = []
    previous: list[dict[str, Any]] = []
    seen: set[str] = set()
    for rule_id, row in current_by_id.items():
        if rule_id in seen or str(row.get("connection_type") or "").casefold() != "bonifico":
            continue
        seen.add(rule_id)
        active.append(dict(row))

    for rule_id, entry in payload.items():
        if rule_id in seen or not entry.get("ever_bonifico"):
            continue
        current = current_by_id.get(rule_id)
        if current and str(current.get("connection_type") or "").casefold() == "bonifico":
            continue
        row = dict(entry)
        row["exists"] = bool(current)
        row["current_connection_type"] = str((current or {}).get("connection_type") or "")
        if current:
            row.update({
                "name": current.get("name", row.get("name")),
                "type": current.get("type", row.get("type")),
                "amount": current.get("amount", row.get("amount")),
                "frequency": current.get("frequency", row.get("frequency")),
            })
        previous.append(row)

    active.sort(key=lambda row: str(row.get("name") or "").casefold())
    previous.sort(key=lambda row: str(row.get("updated_at") or ""), reverse=True)
    return {"active": active, "previous": previous}
