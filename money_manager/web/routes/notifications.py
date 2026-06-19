from __future__ import annotations

from flask import Blueprint, jsonify, request

from money_manager.services.notification_state_service import mark_notifications_read

bp = Blueprint("notifications", __name__, url_prefix="/notifications")


@bp.post("/read")
def mark_read():
    payload = request.get_json(silent=True) or {}

    items = payload.get("items")
    if not isinstance(items, list):
        ids = payload.get("ids", [])
        if not isinstance(ids, list):
            ids = []

        items = [{"id": str(item_id)} for item_id in ids if item_id]

    result = mark_notifications_read(items)
    return jsonify(result)