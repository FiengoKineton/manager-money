from flask import Blueprint, abort, redirect, render_template, request, url_for

from money_manager.services.account_service import (
    account_detail_context,
    accounts_page_context,
    create_custom_account_from_form,
    reconcile_account_balance,
)
from money_manager.services.transaction_service import load_transactions

bp = Blueprint("accounts", __name__, url_prefix="/accounts")


@bp.route("", methods=["GET", "POST"])
def accounts_page():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add_custom_account":
            create_custom_account_from_form(request.form)
        return redirect(url_for("accounts.accounts_page"))

    df = load_transactions()
    return render_template("accounts.html", **accounts_page_context(df))


@bp.route("/<account_key>", methods=["GET", "POST"])
def account_detail(account_key: str):
    df = load_transactions()

    if request.method == "POST":
        action = request.form.get("action")
        if action == "cleanup":
            try:
                target_balance = float(str(request.form.get("target_balance", "0")).replace(",", "."))
            except ValueError:
                target_balance = 0.0
            reconcile_account_balance(
                df,
                account_key=account_key,
                target_balance=target_balance,
                movement_date=request.form.get("date", ""),
                description=request.form.get("description", ""),
            )
            return redirect(url_for("accounts.account_detail", account_key=account_key))

    context = account_detail_context(df, account_key)
    if context is None:
        abort(404)
    return render_template("account_detail.html", **context)
