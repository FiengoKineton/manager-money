from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from money_manager.services.notification_state_service import mark_notifications_read

bp = Blueprint("notifications", __name__, url_prefix="/notifications")


@bp.get("")
@bp.get("/")
def center():
    from money_manager.services.notification_center_service import build_notification_center_context
    from money_manager.web.context import resolve_request_scope, scope_template_context

    selected_scope = resolve_request_scope(request)
    context = build_notification_center_context(selected_scope=selected_scope)
    context.update(scope_template_context(selected_scope))
    return render_template("notifications/center.html", **context)


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