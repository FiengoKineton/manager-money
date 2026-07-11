from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, url_for

from money_manager.services.managed_recurring_service import (
    KIND_BILL,
    KIND_WORK_INCOME,
    archive_item,
    create_item_from_form,
    delete_item,
    execute_pending_from_form,
    mark_checked_from_form,
    page_context,
    update_item_from_form,
)
from money_manager.web.auth import login_required

bp = Blueprint("managed_recurring", __name__)


@bp.route("/bollette", methods=["GET", "POST"])
@login_required
def bills_page():
    return _managed_page(KIND_BILL)


@bp.route("/work-income", methods=["GET", "POST"])
@login_required
def work_income_page():
    return _managed_page(KIND_WORK_INCOME)


def _managed_page(kind: str):
    if request.method == "POST":
        action = str(request.form.get("action") or "").strip()
        item_id = str(request.form.get("item_id") or "").strip()
        if action == "create":
            result = create_item_from_form(kind, request.form)
        elif action == "update":
            result = update_item_from_form(item_id, request.form)
        elif action == "archive":
            result = archive_item(item_id, archived=True)
        elif action == "restore":
            result = archive_item(item_id, archived=False)
        elif action == "delete":
            result = delete_item(item_id)
        elif action == "mark_checked":
            result = mark_checked_from_form(item_id, request.form)
        elif action == "execute_pending":
            result = execute_pending_from_form(request.form)
        else:
            result = {"ok": False, "error": "Unknown action."}

        endpoint = "managed_recurring.bills_page" if kind == KIND_BILL else "managed_recurring.work_income_page"
        query_key = "message" if result.get("ok") else "error"
        query_value = result.get("message") if result.get("ok") else result.get("error", "Not saved.")
        return redirect(url_for(endpoint, **{query_key: query_value}))

    return render_template(
        "planning/managed_recurring.html",
        **page_context(
            kind,
            message=request.args.get("message", ""),
            error=request.args.get("error", ""),
            refresh_automatic=request.headers.get("X-MoneyManager-Warmup", "").strip() != "1",
        ),
    )
