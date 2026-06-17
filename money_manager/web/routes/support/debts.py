from flask import Blueprint, redirect, render_template, request, url_for

from money_manager.services.debt_service import (
    add_debt_from_form,
    add_rule_from_form,
    delete_debt_from_form,
    delete_rule_from_form,
    generate_debt_payments,
    page_context,
    pay_debt_from_form,
    pay_creditor_debts_from_form,
    pay_rule_now_from_form,
    update_debt_from_form,
    update_rule_from_form,
)
bp = Blueprint("debts", __name__, url_prefix="/debts")


@bp.route("", methods=["GET", "POST"])
def debts_page():
    if request.method == "POST":
        action = request.form.get("action")

        if action == "add_debt":
            add_debt_from_form(request.form)
        elif action == "delete_debt":
            delete_debt_from_form(request.form)
        elif action == "update_debt":
            update_debt_from_form(request.form)
        elif action == "pay_debt":
            pay_debt_from_form(request.form)
        elif action == "pay_creditor_debts":
            pay_creditor_debts_from_form(request.form)
        elif action == "add_rule":
            add_rule_from_form(request.form)
        elif action == "delete_rule":
            delete_rule_from_form(request.form)
        elif action == "update_rule":
            update_rule_from_form(request.form)
        elif action == "pay_rule_now":
            pay_rule_now_from_form(request.form)
        elif action == "generate_due":
            generate_debt_payments()

        return redirect(url_for("debts.debts_page"))

    generate_debt_payments()
    return render_template("support/debts.html", **page_context())
