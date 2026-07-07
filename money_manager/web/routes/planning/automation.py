from flask import Blueprint, redirect, render_template, request, url_for

from money_manager.services.smart_rule_service import add_rule_from_form, automation_context, delete_rule_from_form, toggle_rule_from_form

bp = Blueprint("automation", __name__, url_prefix="/automation")


@bp.route("", methods=["GET", "POST"])
def automation_page():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add_rule":
            add_rule_from_form(request.form)
        elif action == "delete_rule":
            delete_rule_from_form(request.form)
        elif action == "toggle_rule":
            toggle_rule_from_form(request.form)
        return redirect(url_for("automation.automation_page"))
    return render_template("planning/automation.html", **automation_context())
