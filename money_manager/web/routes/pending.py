from flask import Blueprint, redirect, render_template, request, url_for

from money_manager.config import CATEGORY_OPTIONS, DEFAULT_CATEGORY_BY_TYPE, account_options_for_forms
from money_manager.repositories.pending import delay_pending, delete_pending, load_pending, update_pending
from money_manager.repositories.recurring import load_recurring
from money_manager.services.debt_service import generate_debt_payments
from money_manager.services.pending_service import execute_pending_by_id, prepare_pending_for_display, process_pending
from money_manager.services.recurring_service import (
    append_rule_from_form,
    delete_rule_from_form,
    generate_recurring,
    prepare_recurring_for_display,
    update_rule_from_form,
)

bp = Blueprint("pending", __name__)


def _pending_update_payload(form) -> dict:
    return {
        "type": form.get("type", "expense"),
        "date_due": form.get("date_due", ""),
        "amount": form.get("amount", "0"),
        "category": form.get("category", ""),
        "account": form.get("account", ""),
        "description": form.get("description", ""),
        "status": form.get("status", "pending"),
    }


@bp.route("/pending", methods=["GET", "POST"])
def pending_page():
    if request.method == "POST":
        action = request.form.get("action")
        row_id = request.form.get("id", "")

        if action == "delete_pending":
            delete_pending(row_id)
        elif action == "delay_pending":
            delay_pending(row_id, request.form.get("delay_date", ""))
        elif action == "execute_pending":
            execute_pending_by_id(row_id, execution_date=request.form.get("date_due", ""))
        elif action == "process_due":
            process_pending()
        elif action == "update_pending":
            payload = _pending_update_payload(request.form)
            if str(payload.get("status", "pending")).lower() == "executed":
                # Update the editable fields first, then create the real transaction.
                payload["status"] = "pending"
                update_pending(row_id, payload)
                execute_pending_by_id(row_id, execution_date=request.form.get("date_due", ""))
            else:
                update_pending(row_id, payload)

        return redirect(url_for("pending.pending_page"))

    generate_recurring()
    generate_debt_payments()
    process_pending(credit_only=True)

    pending_rows = prepare_pending_for_display(load_pending())

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
        account_options=account_options_for_forms(),
    )


@bp.route("/recurring", methods=["GET", "POST"])
def recurring_page():
    if request.method == "POST":
        action = request.form.get("action")

        if action == "add":
            append_rule_from_form(request.form)
        elif action == "update":
            update_rule_from_form(request.form)
        elif action == "delete":
            delete_rule_from_form(request.form)

        return redirect(url_for("pending.recurring_page"))

    generate_recurring()
    process_pending(credit_only=True)
    
    recurring_rows = prepare_recurring_for_display(load_recurring())

    return render_template(
        "recurring.html",
        recurring=recurring_rows,
        categories_by_type=CATEGORY_OPTIONS,
        default_category_by_type=DEFAULT_CATEGORY_BY_TYPE,
        account_options=account_options_for_forms(),
    )
