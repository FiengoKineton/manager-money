from flask import Blueprint, redirect, render_template, request, url_for

from money_manager.services.payable_service import (
    add_payable_from_form,
    delete_payable_from_form,
    page_context,
    pay_payable_from_form,
    update_payable_from_form,
)
from money_manager.web.context import resolve_request_scope, scope_template_context

bp = Blueprint("payables", __name__, url_prefix="/payables")


@bp.route("", methods=["GET", "POST"])
def payables_page():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add_payable":
            add_payable_from_form(request.form)
        elif action == "pay_payable":
            pay_payable_from_form(request.form)
        elif action == "delete_payable":
            delete_payable_from_form(request.form)
        elif action == "update_payable":
            update_payable_from_form(request.form)
        account_id = request.args.get("account_id", "")
        return redirect(url_for("payables.payables_page", account_id=account_id) if account_id else url_for("payables.payables_page"))

    selected_scope = resolve_request_scope(request)
    context = page_context(scope=selected_scope)
    context.update(scope_template_context(selected_scope))
    return render_template("planning/payables.html", **context)