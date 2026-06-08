from flask import Blueprint, redirect, render_template, request, url_for

from money_manager.config import CATEGORY_OPTIONS, DEFAULT_CATEGORY_BY_TYPE, account_options_for_forms
from money_manager.repositories.pending import delete_pending, load_pending
from money_manager.repositories.recurring import load_recurring
from money_manager.services.pending_service import prepare_pending_for_display, process_pending
from money_manager.services.recurring_service import (
    append_rule_from_form,
    delete_rule_from_form,
    generate_recurring,
    prepare_recurring_for_display,
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
        elif action == "delete_pending":
            delete_pending(request.form.get("id", ""))

        return redirect(url_for("pending.pending_page"))

    generate_recurring()
    process_pending()

    pending_rows = prepare_pending_for_display(load_pending())
    recurring_rows = prepare_recurring_for_display(load_recurring())

    return render_template(
        "pending.html",
        pending=pending_rows["all"],
        pending_open=pending_rows["pending"],
        pending_executed=pending_rows["executed"],
        pending_total=pending_rows["pending_total"],
        main_pending_total=pending_rows["main_pending_total"],
        pending_income=pending_rows["pending_income"],
        pending_outflow=pending_rows["pending_outflow"],
        auxiliary_pending=pending_rows["auxiliary_pending"],
        next_pending_date=pending_rows["next_pending_date"],
        recurring=recurring_rows,
        categories_by_type=CATEGORY_OPTIONS,
        default_category_by_type=DEFAULT_CATEGORY_BY_TYPE,
        account_options=account_options_for_forms(),
    )
