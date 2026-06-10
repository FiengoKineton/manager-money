from datetime import date

from flask import Blueprint, redirect, render_template, request, url_for

from money_manager.config import default_date_range
from money_manager.services.sparagnat_service import add_entry_from_form, delete_entry_from_form, page_context, update_entry_from_form

bp = Blueprint("sparagnat", __name__, url_prefix="/sparagnat")


@bp.route("", methods=["GET", "POST"])
def sparagnat_page():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add":
            add_entry_from_form(request.form)
        elif action == "update":
            update_entry_from_form(request.form)
        elif action == "delete":
            delete_entry_from_form(request.form)
        return redirect(url_for("sparagnat.sparagnat_page"))

    start_default, end_default = default_date_range()
    start = request.args.get("from", start_default)
    end = request.args.get("to", end_default)
    context = page_context(start, end)

    return render_template(
        "sparagnat.html",
        **context,
        start=start,
        end=end,
        today=date.today().isoformat(),
    )
