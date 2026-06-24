from datetime import date
import json

from flask import Blueprint, redirect, render_template, request, url_for

from money_manager.config import TRANSACTION_TYPES
from money_manager.domain.transaction import TransactionInput
from money_manager.services.analytics_service import apply_transaction_filters
from money_manager.services.calculation_service import cached_context
from money_manager.services.account_scope_service import transactions_for_scope
from money_manager.services.category_service import category_context
from money_manager.services.currency_service import currency_options_for_forms
from money_manager.services.quick_log_service import handle_quick_log, quick_log_context
from money_manager.services.payment_form_service import payment_form_context
from money_manager.utils.stats import summary_totals
from money_manager.services.transaction_window_service import (
    split_transactions_at,
    totals_with_initial_conditions,
    transaction_default_date_range,
    transaction_initial_conditions_for_frame,
)
from money_manager.web.transaction_filter_state import resolve_transaction_filter_state
from money_manager.web.context import resolve_request_scope, scope_template_context
from money_manager.services.transaction_service import (
    delete_existing_transaction,
    load_transactions,
    prepare_transactions_for_display,
    account_balances_for_preview,
    main_net_for_preview,
    paypal_balance,
    save_new_transaction,
    transaction_detail_context,
    update_existing_transaction,
    delay_existing_transaction,
)

bp = Blueprint("transactions", __name__)


@bp.route("/transactions")
def transactions_page():
    selected_scope = resolve_request_scope(request)
    scope_key = selected_scope["scope"]

    start_default, end_default = transaction_default_date_range()
    filter_state = resolve_transaction_filter_state(request.args, start_default, end_default, TRANSACTION_TYPES)

    params = {
        "scope": scope_key,
        "start": filter_state["start"],
        "end": filter_state["end"],
        "types": tuple(filter_state["types"]),
        "categories": tuple(filter_state["categories"]),
        "query": filter_state["query"],
        "amount_min": filter_state["amount_min"],
        "amount_max": filter_state["amount_max"],
        "has_effective_filters": bool(filter_state.get("has_effective_filters")),
    }

    context = cached_context(
        "transaction_table_view",
        lambda: _build_transactions_page_context(scope_key, filter_state),
        params=params,
    )

    return render_template(
        "core/transactions.html",
        **context,
        **scope_template_context(selected_scope),
    )


def _build_transactions_page_context(scope_key: str, filter_state: dict) -> dict:
    df = load_transactions()
    main_df = transactions_for_scope(df, scope_key)

    start = filter_state["start"]
    end = filter_state["end"]
    types = filter_state["types"]
    categories = filter_state["categories"]
    query = filter_state["query"]
    amount_min = filter_state["amount_min"]
    amount_max = filter_state["amount_max"]
    has_effective_filters = bool(filter_state.get("has_effective_filters"))

    scoped_df = main_df
    filtered = apply_transaction_filters(scoped_df, start, end, types, categories, query, amount_min, amount_max)
    display_rows = filtered.copy()

    historical_df, _recent_df = split_transactions_at(main_df, start)
    initial_conditions = transaction_initial_conditions_for_frame(
        historical_df,
        scope=scope_key,
        start=start,
    )
    calculation_main = filtered if has_effective_filters else filtered
    calculation_totals = summary_totals(calculation_main)
    if not has_effective_filters:
        calculation_totals = totals_with_initial_conditions(calculation_main, initial_conditions)

    filtered = prepare_transactions_for_display(filtered)
    all_categories = sorted(main_df["category"].dropna().unique().tolist()) if not main_df.empty and "category" in main_df.columns else []

    transaction_summary = {
        "count": int(len(display_rows)),
        "income": calculation_totals["income"],
        "expenses": calculation_totals["expenses"],
        "investments": calculation_totals["investments"],
        "net": calculation_totals["net"],
        "opening_net": calculation_totals.get("opening_net", 0.0),
        "recent_net": calculation_totals.get("recent_net", calculation_totals["net"]),
        "savings_rate": calculation_totals["savings_rate"],
        "scope_label": "selected filters" if has_effective_filters else "initial condition + rolling window",
        "uses_full_history_for_calculations": False,
        "uses_transaction_initial_conditions": not has_effective_filters,
        "initial_condition_rows": int(initial_conditions.get("historical_rows", 0) or 0),
    }

    return {
        "transactions": filtered.to_dict(orient="records"),
        "transactions_initial": filtered.head(50).to_dict(orient="records"),
        "transaction_summary": transaction_summary,
        "start": start,
        "end": end,
        "active_types": types,
        "all_types": TRANSACTION_TYPES,
        "categories_selected": categories,
        "categories_all": all_categories,
        "q": query,
        "amount_min": amount_min,
        "amount_max": amount_max,
        "has_effective_filters": has_effective_filters,
        "has_non_date_filters": bool(filter_state.get("has_non_date_filters")),
        "uses_full_history_for_calculations": False,
        "uses_transaction_initial_conditions": not has_effective_filters,
        "visual_scope_label": filter_state.get("display_scope_label", "previous month + current month"),
        "transaction_window": {
            "start": start,
            "end": end,
            "opening_net": float(initial_conditions.get("opening_net", 0.0) or 0.0),
            "historical_rows": int(initial_conditions.get("historical_rows", 0) or 0),
        },
    }

@bp.route("/add", methods=["GET", "POST"])
def add_transaction():
    form_values = {}
    form_error = ""

    quick_error = ""
    quick_message = request.args.get("quick_message", "")
    quick_values = {}

    if request.method == "POST" and request.form.get("action") == "quick_special_log":
        result = handle_quick_log(request.form)
        if result.get("ok"):
            return redirect(url_for("transactions.add_transaction", type=request.args.get("type", "expense"), special="1", quick_message=result.get("message", "Saved.")))
        quick_error = result.get("error", "The special log was not saved.")
        quick_values = request.form.to_dict()
        transaction_type = request.args.get("type", "expense")
    elif request.method == "POST":
        tx_input = TransactionInput.from_form(request.form)
        result = save_new_transaction(tx_input)
        if result.get("ok"):
            scoped_account_id = request.form.get("account_id") or request.args.get("account_id") or ""
            return redirect(url_for("transactions.transactions_page", account_id=scoped_account_id) if scoped_account_id else url_for("transactions.transactions_page"))
        form_error = result.get("error", "The transaction was not saved.")
        form_values = request.form.to_dict()
        transaction_type = tx_input.type
    else:
        transaction_type = request.args.get("type", "expense")

    if transaction_type not in TRANSACTION_TYPES:
        transaction_type = "expense"

    show_special_log = request.args.get("special") == "1" or (request.method == "POST" and request.form.get("action") == "quick_special_log")
    special_context = quick_log_context() if show_special_log else {"quick_log_modes": [], "quick_log_context": {}}

    context = category_context(transaction_type)
    payment_context = payment_form_context(
        transaction_type=transaction_type,
        selected_account_id=form_values.get("account_id") or form_values.get("account") or request.args.get("account_id"),
        selected_payment_method_id=form_values.get("payment_method_id") or request.args.get("payment_method_id"),
    )
    currency_options = currency_options_for_forms()
    return render_template(
        "core/add_transaction.html",
        **context,
        **payment_context,
        today=date.today().isoformat(),
        currency_options=currency_options,
        currency_options_json=json.dumps(currency_options),
        paypal_balance=paypal_balance(),
        account_balances_json=json.dumps(account_balances_for_preview()),
        main_net_preview=main_net_for_preview(),
        form_error=form_error,
        form_values=form_values,
        quick_error=quick_error,
        quick_message=quick_message,
        quick_values=quick_values,
        show_special_log=show_special_log,
        **special_context,
    )


@bp.route("/transaction/<int:row_index>", methods=["GET", "POST"])
def transaction_detail(row_index: int):
    warning = ""
    if request.method == "POST":
        action = request.form.get("action")

        if action == "delete":
            result = delete_existing_transaction(row_index, confirm_settled_edit=request.form.get("confirm_settled_edit") == "1")
            if result.get("ok"):
                scoped_account_id = request.args.get("account_id") or request.form.get("account_id") or ""
                return redirect(url_for("transactions.transactions_page", account_id=scoped_account_id) if scoped_account_id else url_for("transactions.transactions_page"))
            warning = result.get("error", "The transaction was not deleted.")
        
        elif action == "delay":
            result = delay_existing_transaction(row_index, request.form.get("delay_date", ""))
            if result.get("ok"):
                return redirect(request.referrer or url_for("transactions.transactions_page"))
            warning = result.get("error", "The transaction date was not changed.")

        elif action == "update":
            result = update_existing_transaction(row_index, request.form)
            if result.get("ok"):
                return redirect(url_for("transactions.transaction_detail", row_index=row_index))
            warning = result.get("error", "The transaction was not updated.")

    try:
        tx, categories = transaction_detail_context(row_index)
    except LookupError:
        return f"Transaction {row_index} not found", 404

    return render_template(
        "core/transaction_detail.html",
        tx=tx,
        categories=categories,
        **payment_form_context(
            transaction_type=tx.get("type"),
            selected_account_id=tx.get("account_id") or tx.get("account_key") or tx.get("account"),
            selected_payment_method_id=tx.get("payment_method_id"),
        ),
        transaction_warning=warning or request.args.get("warning", ""),
    )
