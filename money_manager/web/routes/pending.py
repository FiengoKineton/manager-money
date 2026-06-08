from flask import Blueprint, redirect, render_template, request, url_for

from money_manager.config import CATEGORY_OPTIONS, DEFAULT_CATEGORY_BY_TYPE
from money_manager.repositories.pending import load_pending
from money_manager.repositories.recurring import load_recurring
from money_manager.services.pending_service import process_pending
from money_manager.services.recurring_service import (
    append_rule_from_form,
    delete_rule_from_form,
    generate_recurring,
    next_due_date_for_rule,
    update_rule_from_form,
)

bp = Blueprint("pending", __name__)


@bp.route("/pending", methods=["GET", "POST"])
def pending_page():
    if request.method == "POST":
        action = request.form.get("action")

        if action == "add":
            append_rule_from_form(request.form)
        elif action == "update":
            update_rule_from_form(request.form)
        elif action == "delete":
            delete_rule_from_form(request.form)

        return redirect(url_for("pending.pending_page"))

    generate_recurring()
    process_pending()

    pending_rows = load_pending()
    recurring_rows = load_recurring()

    for row in recurring_rows:
        row["next_payment"] = next_due_date_for_rule(row).isoformat()

    return render_template(
        "pending.html",
        pending=pending_rows,
        recurring=recurring_rows,
        categories_by_type=CATEGORY_OPTIONS,
        default_category_by_type=DEFAULT_CATEGORY_BY_TYPE,
    )
