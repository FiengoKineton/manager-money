from datetime import date

from flask import Blueprint, redirect, render_template, request, url_for

from money_manager.config import default_date_range
from money_manager.services.parent_support_service import (
    add_entry_from_form,
    add_rule_from_form,
    delete_entry_from_form,
    delete_rule_from_form,
    page_context,
)

bp = Blueprint("parent_support", __name__, url_prefix="/parents")


@bp.route("", methods=["GET", "POST"])
def parent_support_page():
    if request.method == "POST":
        action = request.form.get("action")

        if action == "add_rule":
            add_rule_from_form(request.form)
        elif action == "delete_rule":
            delete_rule_from_form(request.form)

        # Optional old compatibility.
        elif action == "add":
            add_entry_from_form(request.form)
        elif action == "delete":
            delete_entry_from_form(request.form)

        return redirect(url_for("parent_support.parent_support_page"))

    start_default, end_default = default_date_range()
    start = request.args.get("from", start_default)
    end = request.args.get("to", end_default)

    return render_template(
        "parent_support.html",
        **page_context(start, end),
        start=start,
        end=end,
        today=date.today().isoformat(),
    )
