from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, url_for

from money_manager.services.planned_expense_service import (
    create_planned_expense_from_form,
    delete_planned_expense_from_form,
    mark_planned_expense_paid_from_form,
    page_context,
    update_planned_expense_from_form,
)

bp = Blueprint("planned_expenses", __name__, url_prefix="/planning/planned-expenses")


@bp.route("", methods=["GET", "POST"])
def planned_expenses_page():
    message = ""
    error = ""
    if request.method == "POST":
        action = str(request.form.get("action") or "").strip()
        if action == "create_planned_expense":
            result = create_planned_expense_from_form(request.form)
        elif action == "update_planned_expense":
            result = update_planned_expense_from_form(request.form)
        elif action == "pay_planned_expense":
            result = mark_planned_expense_paid_from_form(request.form)
        elif action == "delete_planned_expense":
            result = delete_planned_expense_from_form(request.form)
        else:
            result = {"ok": False, "error": "Unknown action."}
        if result.get("ok"):
            message = str(result.get("message") or "Saved.")
        else:
            error = str(result.get("error") or "Could not save.")
        return redirect(url_for("planned_expenses.planned_expenses_page", message=message, error=error))

    return render_template(
        "planning/planned_expenses.html",
        **page_context(message=request.args.get("message", ""), error=request.args.get("error", "")),
    )
