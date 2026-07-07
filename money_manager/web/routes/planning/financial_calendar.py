from __future__ import annotations

from flask import Blueprint, render_template, request

from money_manager.services.financial_calendar_service import build_financial_calendar_context
from money_manager.web.context import resolve_request_scope, scope_template_context

bp = Blueprint("financial_calendar", __name__, url_prefix="/calendar")


@bp.get("")
def calendar_page():
    selected_scope = resolve_request_scope(request)
    context = build_financial_calendar_context(
        selected_scope=selected_scope,
        month=request.args.get("month", ""),
    )
    context.update(scope_template_context(selected_scope))
    return render_template("planning/financial_calendar.html", **context)
