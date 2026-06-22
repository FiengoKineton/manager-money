from flask import Blueprint, abort, redirect, render_template, request, url_for

from money_manager.services.account_service import (
    account_detail_context,
    accounts_page_context,
    add_card_from_form,
    archive_account_from_form,
    archive_card_from_form,
    create_custom_account_from_form,
    reconcile_account_balance,
    restore_account_from_form,
    update_account_settings_from_form,
)
from money_manager.services.transaction_service import load_transactions
from money_manager.services.pending_service import process_pending, sync_credit_account_statements

bp = Blueprint("accounts", __name__, url_prefix="/accounts")


def _refresh_credit_statements() -> None:
    sync_credit_account_statements()
    process_pending(credit_only=True)


@bp.route("", methods=["GET", "POST"])
def accounts_page():
    if request.method == "POST":
        action = request.form.get("action")
        if action in {"add_custom_account", "add_account"}:
            create_custom_account_from_form(request.form)
        elif action == "archive_account":
            archive_account_from_form(request.form.get("account_key", ""))
        elif action == "restore_account":
            restore_account_from_form(request.form.get("account_key", ""))
        return redirect(url_for("accounts.accounts_page"))

    _refresh_credit_statements()
    df = load_transactions()
    return render_template("accounts/accounts.html", **accounts_page_context(df))


@bp.route("/<account_key>", methods=["GET", "POST"])
def account_detail(account_key: str):
    _refresh_credit_statements()
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
        if action == "update_account":
            update_account_settings_from_form(account_key, request.form)
            return redirect(url_for("accounts.account_detail", account_key=account_key))
        if action == "archive_account":
            archive_account_from_form(account_key)
            return redirect(url_for("accounts.accounts_page"))
        if action == "restore_account":
            restore_account_from_form(account_key)
            return redirect(url_for("accounts.account_detail", account_key=account_key))
        if action == "add_card":
            add_card_from_form(account_key, request.form)
            return redirect(url_for("accounts.account_detail", account_key=account_key))
        if action == "archive_card":
            archive_card_from_form(account_key, request.form.get("card_id", ""))
            return redirect(url_for("accounts.account_detail", account_key=account_key))

    context = account_detail_context(df, account_key)
    if context is None:
        abort(404)
    return render_template("accounts/account_detail.html", **context)
