from __future__ import annotations

import threading
from datetime import datetime
from typing import Any

from money_manager.config.paths import NOTIFICATIONS_STATE_JSON
from money_manager.security.secure_storage import read_json_secure, write_json_secure

_LOCK = threading.RLock()
MAX_HISTORY = 120


def _empty_state() -> dict[str, Any]:
    return {
        "version": 1,
        "read": {},
        "history": [],
    }


def load_notification_state() -> dict[str, Any]:
    with _LOCK:
        try:
            state = read_json_secure(NOTIFICATIONS_STATE_JSON, default=None)
            if state is None:
                return _empty_state()

            if not isinstance(state, dict):
                return _empty_state()

            state.setdefault("version", 1)
            state.setdefault("read", {})
            state.setdefault("history", [])
            return state
        except Exception:
            return _empty_state()


def save_notification_state(state: dict[str, Any]) -> None:
    with _LOCK:
        try:
            write_json_secure(NOTIFICATIONS_STATE_JSON, state)
        except Exception:
            return


def read_notification_ids() -> set[str]:
    state = load_notification_state()
    read = state.get("read", {})
    if not isinstance(read, dict):
        return set()
    return set(str(key) for key in read.keys())


def notification_history(limit: int = 20) -> list[dict[str, Any]]:
    state = load_notification_state()
    history = state.get("history", [])
    if not isinstance(history, list):
        return []

    clean = [item for item in history if isinstance(item, dict) and item.get("id")]
    return clean[:limit]


def mark_notifications_read(items: list[dict[str, Any]]) -> dict[str, Any]:
    state = load_notification_state()
    read = state.setdefault("read", {})
    history = state.setdefault("history", [])

    if not isinstance(read, dict):
        read = {}
        state["read"] = read

    if not isinstance(history, list):
        history = []
        state["history"] = history

    now = datetime.now().isoformat(timespec="seconds")

    history_by_id = {
        str(item.get("id")): item
        for item in history
        if isinstance(item, dict) and item.get("id")
    }

    for item in items:
        if not isinstance(item, dict):
            continue

        item_id = str(item.get("id", "")).strip()
        if not item_id:
            continue

        read[item_id] = now

        saved_item = {
            "id": item_id,
            "tone": item.get("tone", "info"),
            "label": item.get("label", "Reminder"),
            "icon": item.get("icon", "•"),
            "title": item.get("title", "Notification"),
            "summary": item.get("summary", ""),
            "detail": item.get("detail", ""),
            "meta": item.get("meta", ""),
            "href": item.get("href", ""),
            "href_label": item.get("href_label", "Open"),
            "read_at": now,
            "last_seen_at": now,
        }

        history_by_id[item_id] = saved_item

    ordered_history = sorted(
        history_by_id.values(),
        key=lambda row: str(row.get("read_at", "")),
        reverse=True,
    )

    state["history"] = ordered_history[:MAX_HISTORY]
    save_notification_state(state)

    return {
        "ok": True,
        "read_count": len(read),
        "history_count": len(state["history"]),
    }