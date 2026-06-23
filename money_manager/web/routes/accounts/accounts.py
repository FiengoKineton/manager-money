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
from money_manager.services.account_calculation_service import get_account_dashboard_summary_cached
from money_manager.services.calculation_service import cached_context
from money_manager.services.pending_service import process_pending, sync_credit_account_statements
from money_manager.services.account_closure_service import account_closure_precheck, close_account
from money_manager.services.account_config_service import all_accounts, set_default_account
from money_manager.services.account_integrity_service import full_integrity_report
from money_manager.services.payment_form_service import account_options_for_payment_forms, explain_payment_method, payment_method_options_for_forms
from money_manager.services.payment_method_service import (
    archive_payment_method,
    create_payment_method_from_form,
    restore_payment_method,
    set_default_payment_method,
    update_payment_method_from_form,
)
from money_manager.services.profile_service import load_profile, update_profile
from money_manager.web.context import scope_template_context

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
        elif action == "set_default_account":
            account_key = request.form.get("account_key", "")
            if set_default_account(account_key):
                update_profile({"default_current_account_id": account_key})
        elif action == "add_payment_method":
            method = create_payment_method_from_form(request.form)
            if request.form.get("is_default") and method.get("id"):
                set_default_payment_method(method["id"])
                update_profile({"default_payment_method_id": method["id"]})
        elif action == "update_payment_method":
            method_id = request.form.get("payment_method_id", "")
            method = update_payment_method_from_form(method_id, request.form)
            if request.form.get("is_default") and method.get("id"):
                set_default_payment_method(method["id"])
                update_profile({"default_payment_method_id": method["id"]})
        elif action == "archive_payment_method":
            archive_payment_method(request.form.get("payment_method_id", ""))
        elif action == "restore_payment_method":
            restore_payment_method(request.form.get("payment_method_id", ""))
        if "payment_method" in str(action):
            return redirect(url_for("accounts.accounts_page", _anchor="payment-methods"))
        return redirect(url_for("accounts.accounts_page"))

    _refresh_credit_statements()
    df = load_transactions()
    context = get_account_dashboard_summary_cached()
    context.update(_account_settings_context())
    return render_template("accounts/accounts.html", **context, **scope_template_context("global"))


def _account_settings_context() -> dict:
    integrity = full_integrity_report()
    profile = load_profile()
    payment_methods = payment_method_options_for_forms(include_archived=True)
    for method in payment_methods:
        method["explanation"] = explain_payment_method(method.get("id"))
    return {
        "profile": profile,
        "payment_methods": payment_methods,
        "payment_account_options": account_options_for_payment_forms(include_archived=True, include_credit=True),
        "parent_account_options": _parent_account_options_for_linking(),
        "payment_method_options_all": payment_methods,
        "integrity_warnings": integrity.get("warnings", [])[:12],
        "integrity_errors": integrity.get("errors", [])[:12],
        "method_type_options": [
            "bank_transfer", "debit_card", "credit_card", "prepaid_card", "cash",
            "wallet_balance", "wallet_linked_card", "meal_voucher",
            "investment_cash_transfer", "other",
        ],
        "settlement_mode_options": ["immediate", "stored_balance", "delayed", "delegated", "external_record_only"],
    }


def _parent_account_options_for_linking() -> list[dict]:
    options: list[dict] = []
    for account in all_accounts(include_archived=False, include_main=True):
        key = str(account.get("key") or account.get("id") or "")
        kind = str(account.get("account_kind") or account.get("type") or "")
        if not key or kind == "credit_card_liability" or account.get("is_liability"):
            continue
        if not (account.get("is_current_account") or account.get("is_container") or kind in {"current_account", "container"}):
            continue
        options.append({
            "key": key,
            "value": key,
            "label": str(account.get("label") or account.get("name") or key),
            "account_kind": kind,
            "is_current_account": bool(account.get("is_current_account") or kind == "current_account"),
            "is_container": bool(account.get("is_container") or kind == "container"),
        })
    return sorted(options, key=lambda item: (0 if item.get("is_current_account") else 1, str(item.get("label") or "")))


@bp.route("/<account_key>", methods=["GET", "POST"])
def account_detail(account_key: str):
    _refresh_credit_statements()
    df = load_transactions()
    error = ""
    message = request.args.get("message", "")

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
        if action == "set_default_account":
            if set_default_account(account_key):
                update_profile({"default_current_account_id": account_key})
            return redirect(url_for("accounts.account_detail", account_key=account_key))
        if action == "close_account":
            result = close_account(account_key, request.form)
            if result.get("ok"):
                return redirect(url_for("accounts.accounts_page"))
            error = result.get("error", "Account cannot be closed safely yet.")
        if action == "add_card":
            add_card_from_form(account_key, request.form)
            return redirect(url_for("accounts.account_detail", account_key=account_key))
        if action == "archive_card":
            archive_card_from_form(account_key, request.form.get("card_id", ""))
            return redirect(url_for("accounts.account_detail", account_key=account_key))
        if action == "create_account_card_method":
            card_type = str(request.form.get("method_type") or "debit_card").strip()
            settlement_mode = {
                "debit_card": "immediate",
                "credit_card": "delayed",
                "prepaid_card": "stored_balance",
            }.get(card_type, "immediate")
            card_form = dict(request.form)
            card_form.update({
                "method_type": card_type,
                "settlement_mode": settlement_mode,
                "linked_account_id": account_key,
                "funding_account_id": account_key,
                "settlement_account_id": account_key,
                "is_active": "1",
            })
            if card_type != "credit_card":
                card_form["liability_account_id"] = ""
            method = create_payment_method_from_form(card_form)
            if method.get("id"):
                return redirect(url_for("accounts.account_payment_method_detail", account_key=account_key, method_id=method["id"], _anchor="payment-method-detail"))
            return redirect(url_for("accounts.account_detail", account_key=account_key))

    context = cached_context("account_detail_summary", lambda: account_detail_context(df, account_key), params={"account_key": account_key})
    if context is None:
        abort(404)
    context["closure_precheck"] = account_closure_precheck(account_key)
    context["closure_error"] = error
    context["closure_message"] = message
    context["profile"] = load_profile()
    return render_template("accounts/account_detail.html", **context, **scope_template_context(f"account:{account_key}"))

@bp.route("/<account_key>/payment-methods/<method_id>", methods=["GET", "POST"])
def account_payment_method_detail(account_key: str, method_id: str):
    _refresh_credit_statements()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "update_payment_method":
            update_payment_method_from_form(method_id, request.form)
        elif action == "archive_payment_method":
            archive_payment_method(method_id)
        elif action == "restore_payment_method":
            restore_payment_method(method_id)
        return redirect(url_for("accounts.account_payment_method_detail", account_key=account_key, method_id=method_id))

    df = load_transactions()
    context = cached_context("account_detail_summary", lambda: account_detail_context(df, account_key), params={"account_key": account_key, "method_id": method_id})
    if context is None:
        abort(404)
    selected = None
    for method in context.get("payment_methods", []):
        if str(method.get("id") or "") == str(method_id):
            selected = method
            break
    if selected is None:
        abort(404)
    context["selected_payment_method_id"] = method_id
    context["selected_payment_method"] = selected
    context["closure_precheck"] = account_closure_precheck(account_key)
    context["closure_error"] = ""
    context["closure_message"] = ""
    context["profile"] = load_profile()
    return render_template("accounts/account_detail.html", **context, **scope_template_context(f"account:{account_key}"))

