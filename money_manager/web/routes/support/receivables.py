from flask import Blueprint, redirect, render_template, request, url_for

from money_manager.services.account_service import auxiliary_total, main_account_transactions
from money_manager.services.receivable_service import (
    add_receivable_from_form,
    collect_receivable_from_form,
    delete_receivable_from_form,
    page_context,
    update_receivable_from_form,
)
from money_manager.services.transaction_service import load_transactions
from money_manager.utils.stats import summary_totals

bp = Blueprint("receivables", __name__, url_prefix="/receivables")


@bp.route("", methods=["GET", "POST"])
def receivables_page():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add_receivable":
            add_receivable_from_form(request.form)
        elif action == "collect_receivable":
            collect_receivable_from_form(request.form)
        elif action == "delete_receivable":
            delete_receivable_from_form(request.form)
        elif action == "update_receivable":
            update_receivable_from_form(request.form)
        return redirect(url_for("receivables.receivables_page"))

    transactions = load_transactions()
    totals = summary_totals(main_account_transactions(transactions))
    visible_liquidity = totals["net"] + auxiliary_total(transactions)
    return render_template("receivables.html", **page_context(totals["net"], visible_liquidity))
