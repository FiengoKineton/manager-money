from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, url_for

from money_manager.services.savings_goal_service import (
    add_contribution_from_form,
    create_goal_from_form,
    delete_goal_from_form,
    page_context,
    update_goal_from_form,
)

bp = Blueprint("savings_goals", __name__, url_prefix="/planning/savings-goals")


@bp.route("", methods=["GET", "POST"])
def savings_goals_page():
    message = ""
    error = ""
    if request.method == "POST":
        action = str(request.form.get("action") or "").strip()
        if action == "create_goal":
            result = create_goal_from_form(request.form)
        elif action == "update_goal":
            result = update_goal_from_form(request.form)
        elif action == "add_contribution":
            result = add_contribution_from_form(request.form)
        elif action == "delete_goal":
            result = delete_goal_from_form(request.form)
        else:
            result = {"ok": False, "error": "Unknown action."}
        if result.get("ok"):
            message = str(result.get("message") or "Saved.")
        else:
            error = str(result.get("error") or "Could not save.")
        return redirect(url_for("savings_goals.savings_goals_page", message=message, error=error))

    return render_template(
        "planning/savings_goals.html",
        **page_context(message=request.args.get("message", ""), error=request.args.get("error", "")),
    )
