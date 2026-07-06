from flask import Blueprint, abort, jsonify, redirect, render_template, request, url_for
from time import monotonic
import threading

from money_manager.services.account_service import (
    account_detail_context,
    accounts_page_context,
    add_card_from_form,
    archive_account_from_form,
    archive_card_from_form,
    create_custom_account_from_form,
    ensure_prepaid_card_balance_account,
    ensure_credit_card_liability_account,
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
from money_manager.web.auth import current_user
from money_manager.config.user_paths import using_user

bp = Blueprint("accounts", __name__, url_prefix="/accounts")

_CREDIT_REFRESH_INTERVAL_SECONDS = 60
_credit_refresh_lock = threading.RLock()
_credit_refresh_running: set[str] = set()
_last_credit_refresh_at_by_user: dict[str, float] = {}


def _current_user_id() -> str:
    user = current_user() or {}
    return str(user.get("id") or "").strip()


def _refresh_credit_statements_sync(user_id: str) -> None:
    with using_user(user_id):
        sync_credit_account_statements()
        process_pending(credit_only=True)


def _schedule_credit_refresh(*, force: bool = False) -> None:
    """Refresh credit statements after the page is already allowed to render.

    The old route ran credit statement sync + pending processing directly inside
    normal GET requests.  With encrypted CSVs and larger data folders this can
    turn a simple navigation click into a long write-heavy request or a 504.
    """
    user_id = _current_user_id()
    if not user_id:
        return

    now = monotonic()
    with _credit_refresh_lock:
        last_run = _last_credit_refresh_at_by_user.get(user_id, 0.0)
        if not force and now - last_run < _CREDIT_REFRESH_INTERVAL_SECONDS:
            return
        if user_id in _credit_refresh_running:
            return
        _credit_refresh_running.add(user_id)

    def _run() -> None:
        try:
            _refresh_credit_statements_sync(user_id)
            with _credit_refresh_lock:
                _last_credit_refresh_at_by_user[user_id] = monotonic()
        finally:
            with _credit_refresh_lock:
                _credit_refresh_running.discard(user_id)

    thread = threading.Thread(target=_run, name=f"money-manager-credit-refresh-{user_id}", daemon=True)
    thread.start()


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

    _schedule_credit_refresh()
    context = get_account_dashboard_summary_cached()
    context.update(_account_settings_context())
    return render_template("accounts/accounts.html", **context, **scope_template_context("global"))


def _account_settings_context() -> dict:
    # Keep the normal All Conti page light.  The full integrity report touches
    # many CSV/config files and is now exposed through a lazy endpoint instead of
    # blocking every account navigation.
    profile = load_profile()
    return {
        "profile": profile,
        "payment_methods": [],
        "payment_account_options": [],
        "parent_account_options": _parent_account_options_for_linking(),
        "payment_method_options_all": [],
        "integrity_warnings": [],
        "integrity_errors": [],
        "integrity_lazy": True,
        "method_type_options": [
            "bank_transfer", "debit_card", "credit_card", "prepaid_card", "cash",
            "wallet_balance", "wallet_linked_card", "meal_voucher",
            "investment_cash_transfer", "other",
        ],
        "settlement_mode_options": ["immediate", "stored_balance", "delayed", "delegated", "external_record_only"],
    }


@bp.get("/integrity.json")
def account_integrity_json():
    integrity = full_integrity_report()
    return jsonify({
        "ok": True,
        "warnings": integrity.get("warnings", [])[:12],
        "errors": integrity.get("errors", [])[:12],
    })


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
    if request.method == "GET":
        _schedule_credit_refresh()
    error = ""
    message = request.args.get("message", "")

    if request.method == "POST":
        action = request.form.get("action")
        if action == "cleanup":
            try:
                target_balance = float(str(request.form.get("target_balance", "0")).replace(",", "."))
            except ValueError:
                target_balance = 0.0
            df = load_transactions()
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
            card_account_key = account_key
            liability_account_key = str(card_form.get("liability_account_id") or "").strip()
            if card_type == "prepaid_card":
                card_account_key = ensure_prepaid_card_balance_account(
                    account_key,
                    card_form.get("name") or card_form.get("label") or "Prepaid card",
                )
            elif card_type == "credit_card":
                liability_account_key = liability_account_key or ensure_credit_card_liability_account(
                    account_key,
                    card_form.get("name") or card_form.get("label") or "Credit card",
                )

            if card_type == "credit_card":
                linked_account_id = account_key
                funding_account_id = account_key
                settlement_account_id = account_key
            else:
                linked_account_id = card_account_key
                funding_account_id = card_account_key
                settlement_account_id = card_account_key

            card_form.update({
                "method_type": card_type,
                "settlement_mode": settlement_mode,
                "linked_account_id": linked_account_id,
                "funding_account_id": funding_account_id,
                "settlement_account_id": settlement_account_id,
                "parent_account_id": account_key,
                "is_active": "1",
            })
            if card_type == "credit_card":
                card_form["liability_account_id"] = liability_account_key
            else:
                card_form["liability_account_id"] = ""
            method = create_payment_method_from_form(card_form)
            if method.get("id"):
                return redirect(url_for("accounts.account_payment_method_detail", account_key=account_key, method_id=method["id"], _anchor="payment-method-detail"))
            return redirect(url_for("accounts.account_detail", account_key=account_key))

    context = cached_context(
        "account_detail_summary",
        lambda: account_detail_context(load_transactions(), account_key),
        params={"account_key": account_key},
    )
    if context is None:
        abort(404)
    context["closure_precheck"] = account_closure_precheck(account_key)
    context["closure_error"] = error
    context["closure_message"] = message
    context["profile"] = load_profile()
    return render_template("accounts/account_detail.html", **context, **scope_template_context(f"account:{account_key}"))

@bp.route("/<account_key>/payment-methods/<method_id>", methods=["GET", "POST"])
def account_payment_method_detail(account_key: str, method_id: str):
    if request.method == "GET":
        _schedule_credit_refresh()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "update_payment_method":
            update_payment_method_from_form(method_id, request.form)
        elif action == "archive_payment_method":
            archive_payment_method(method_id)
        elif action == "restore_payment_method":
            restore_payment_method(method_id)
        return redirect(url_for("accounts.account_payment_method_detail", account_key=account_key, method_id=method_id))

    context = cached_context(
        "account_detail_summary",
        lambda: account_detail_context(load_transactions(), account_key),
        params={"account_key": account_key},
    )
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

