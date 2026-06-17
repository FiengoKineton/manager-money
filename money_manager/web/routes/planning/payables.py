from flask import Blueprint, redirect, render_template, request, url_for

from money_manager.services.account_service import auxiliary_total, main_account_transactions
from money_manager.services.payable_service import (
    add_payable_from_form,
    delete_payable_from_form,
    page_context,
    pay_payable_from_form,
    update_payable_from_form,
)
from money_manager.services.transaction_service import load_transactions
from money_manager.utils.stats import summary_totals

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
        return redirect(url_for("payables.payables_page"))

    transactions = load_transactions()
    totals = summary_totals(main_account_transactions(transactions))
    visible_liquidity = totals["net"] + auxiliary_total(transactions)
    return render_template("planning/payables.html", **page_context(totals["net"], visible_liquidity))
