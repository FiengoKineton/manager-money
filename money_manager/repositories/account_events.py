from __future__ import annotations

import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from money_manager.config.paths import ACCOUNT_EVENTS_JSON
from money_manager.security.protection_manager import read_json, write_json_atomic

DEFAULT_EVENTS = {"schema_version": 1, "events": []}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_events() -> dict[str, Any]:
    payload = read_json(ACCOUNT_EVENTS_JSON, deepcopy(DEFAULT_EVENTS))
    if not isinstance(payload, dict):
        payload = deepcopy(DEFAULT_EVENTS)
    payload.setdefault("schema_version", 1)
    if not isinstance(payload.get("events"), list):
        payload["events"] = []
    return payload


def write_events(payload: dict[str, Any]) -> None:
    fixed = deepcopy(DEFAULT_EVENTS)
    fixed.update(payload if isinstance(payload, dict) else {})
    if not isinstance(fixed.get("events"), list):
        fixed["events"] = []
    write_json_atomic(ACCOUNT_EVENTS_JSON, fixed)


def append_event(event: dict[str, Any]) -> dict[str, Any]:
    payload = load_events()
    row = {
        "id": event.get("id") or uuid.uuid4().hex,
        "event_type": event.get("event_type") or "account_event",
        "account_id": event.get("account_id") or "",
        "replacement_account_id": event.get("replacement_account_id") or "",
        "status": event.get("status") or "completed",
        "created_at": event.get("created_at") or utc_now(),
        "completed_at": event.get("completed_at") or utc_now(),
        "details": event.get("details") if isinstance(event.get("details"), dict) else {},
        "warnings": event.get("warnings") if isinstance(event.get("warnings"), list) else [],
    }
    payload["events"].append(row)
    write_events(payload)
    return row
