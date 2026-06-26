from flask import Blueprint, redirect, render_template, request, url_for

from money_manager.services.payment_form_service import account_options_for_payment_forms, payment_method_options_for_forms
from money_manager.services.custom_category_service import effective_categories_by_type, default_category_for
from money_manager.repositories.pending import delay_pending, delete_pending, load_pending, mark_discarded, update_pending
from money_manager.repositories.recurring import load_recurring
from money_manager.services.debt_service import generate_debt_payments
from money_manager.services.pending_service import execute_pending_by_id, prepare_pending_for_display, process_pending, sync_credit_account_statements, pending_context_for_scope
from money_manager.services.credit_settlement_service import discard_credit_settlement, discard_credit_settlement_for_pending, execute_credit_settlement, preview_credit_settlements, sync_credit_settlements
from money_manager.web.context import resolve_request_scope, scope_template_context
from money_manager.services.recurring_service import (
    append_rule_from_form,
    delete_rule_from_form,
    generate_recurring,
    prepare_recurring_sections,
    recurring_forecast_for_next_month,
    update_rule_from_form,
    recurring_context_for_scope,
)

bp = Blueprint("pending", __name__)


def _pending_update_payload(form) -> dict:
    return {
        "type": form.get("type", "expense"),
        "date_due": form.get("date_due", ""),
        "amount": form.get("amount", "0"),
        "category": form.get("category", ""),
        "account": form.get("account", ""),
        "account_id": form.get("account_id") or form.get("account", ""),
        "payment_method_id": form.get("payment_method_id", ""),
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
        elif action == "discard_pending":
            result = discard_credit_settlement_for_pending(row_id)
            if not result.get("handled"):
                mark_discarded(row_id)
        elif action == "discard_credit_settlement":
            discard_credit_settlement(request.form.get("settlement_id", ""))
        elif action == "execute_pending":
            execute_pending_by_id(row_id, execution_date=request.form.get("date_due", ""))
        elif action == "execute_credit_settlement":
            execute_credit_settlement(request.form.get("settlement_id", ""), execution_date=request.form.get("execution_date", ""))
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

        account_id = request.args.get("account_id", "")
        return redirect(url_for("pending.pending_page", account_id=account_id) if account_id else url_for("pending.pending_page"))

    generate_recurring()
    generate_debt_payments()
    sync_credit_account_statements()
    sync_credit_settlements(sync_pending=True)
    process_pending(credit_only=True)

    selected_scope = resolve_request_scope(request)
    pending_context = pending_context_for_scope(selected_scope)
    pending_rows = prepare_pending_for_display(pending_context.get("all", load_pending()))
    credit_settlements = preview_credit_settlements()
    recurring_forecast = recurring_forecast_for_next_month()

    return render_template(
        "planning/pending.html",
        pending=pending_rows["all"],
        pending_open=pending_rows["pending"],
        pending_executed=pending_rows["executed"],
        pending_discarded=pending_rows.get("discarded", []),
        pending_total=pending_rows["pending_total"],
        main_pending_total=pending_rows["main_pending_total"],
        pending_income=pending_rows["pending_income"],
        pending_outflow=pending_rows["pending_outflow"],
        auxiliary_pending=pending_rows["auxiliary_pending"],
        next_pending_date=pending_rows["next_pending_date"],
        recurring_forecast=recurring_forecast,
        credit_settlements=credit_settlements,
        account_options=account_options_for_payment_forms(),
        payment_method_options=payment_method_options_for_forms(),
        **scope_template_context(selected_scope),
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

        account_id = request.args.get("account_id", "")
        return redirect(url_for("pending.recurring_page", account_id=account_id) if account_id else url_for("pending.recurring_page"))

    generate_recurring()
    sync_credit_account_statements()
    process_pending(credit_only=True)
    
    selected_scope = resolve_request_scope(request)
    recurring_context = recurring_context_for_scope(selected_scope)
    recurring_sections = prepare_recurring_sections(recurring_context.get("all", load_recurring()))

    return render_template(
        "planning/recurring.html",
        recurring=recurring_sections["active"],
        recurring_finished=recurring_sections["finished"],
        recurring_all=recurring_sections["all"],
        categories_by_type=effective_categories_by_type(),
        default_category_by_type={transaction_type: default_category_for(transaction_type) for transaction_type in effective_categories_by_type()},
        account_options=account_options_for_payment_forms(),
        payment_method_options=payment_method_options_for_forms(),
        **scope_template_context(selected_scope),
    )
