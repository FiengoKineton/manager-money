from datetime import date
import json

from flask import Blueprint, redirect, render_template, request, url_for

from money_manager.config import TRANSACTION_TYPES, account_options_for_forms, default_date_range
from money_manager.domain.transaction import TransactionInput
from money_manager.services.account_service import main_account_transactions
from money_manager.services.analytics_service import apply_transaction_filters
from money_manager.services.category_service import category_context
from money_manager.services.currency_service import currency_options_for_forms
from money_manager.services.quick_log_service import handle_quick_log, quick_log_context
from money_manager.utils.stats import summary_totals
from money_manager.web.transaction_filter_state import resolve_transaction_filter_state
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
    df = load_transactions()
    main_df = main_account_transactions(df)

    start_default, end_default = default_date_range()
    filter_state = resolve_transaction_filter_state(request.args, start_default, end_default, TRANSACTION_TYPES)
    start = filter_state["start"]
    end = filter_state["end"]
    types = filter_state["types"]
    categories = filter_state["categories"]
    query = filter_state["query"]
    amount_min = filter_state["amount_min"]
    amount_max = filter_state["amount_max"]

    has_effective_filters = bool(filter_state.get("has_effective_filters"))

    # The table is visual and follows the active window/filters. The money
    # summary uses full historical main-net rows by default, so older opening
    # transactions still count. When the user actually changes filters, the
    # summary switches to that selected scope.
    filtered = apply_transaction_filters(df, start, end, types, categories, query, amount_min, amount_max)
    display_rows = filtered.copy()
    calculation_main = main_account_transactions(filtered) if has_effective_filters else main_df
    calculation_totals = summary_totals(calculation_main)
    filtered = prepare_transactions_for_display(filtered)
    all_categories = sorted(main_df["category"].dropna().unique().tolist()) if not main_df.empty else []

    transaction_summary = {
        "count": int(len(display_rows)),
        "income": calculation_totals["income"],
        "expenses": calculation_totals["expenses"],
        "investments": calculation_totals["investments"],
        "net": calculation_totals["net"],
        "savings_rate": calculation_totals["savings_rate"],
        "scope_label": "selected filters" if has_effective_filters else "full history",
        "uses_full_history_for_calculations": not has_effective_filters,
    }

    return render_template(
        "core/transactions.html",
        transactions=filtered.to_dict(orient="records"),
        transactions_initial=filtered.head(50).to_dict(orient="records"),
        transaction_summary=transaction_summary,
        start=start,
        end=end,
        active_types=types,
        all_types=TRANSACTION_TYPES,
        categories_selected=categories,
        categories_all=all_categories,
        q=query,
        amount_min=amount_min,
        amount_max=amount_max,
        has_effective_filters=has_effective_filters,
        has_non_date_filters=bool(filter_state.get("has_non_date_filters")),
        uses_full_history_for_calculations=not has_effective_filters,
        visual_scope_label=filter_state.get("display_scope_label", "current year"),
    )


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
            return redirect(url_for("transactions.transactions_page"))
        form_error = result.get("error", "The transaction was not saved.")
        form_values = request.form.to_dict()
        transaction_type = tx_input.type
    else:
        transaction_type = request.args.get("type", "expense")

    if transaction_type not in TRANSACTION_TYPES:
        transaction_type = "expense"

    context = category_context(transaction_type)
    currency_options = currency_options_for_forms()
    return render_template(
        "core/add_transaction.html",
        **context,
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
        show_special_log=request.args.get("special") == "1",
        **quick_log_context(),
    )


@bp.route("/transaction/<int:row_index>", methods=["GET", "POST"])
def transaction_detail(row_index: int):
    if request.method == "POST":
        action = request.form.get("action")

        if action == "delete":
            delete_existing_transaction(row_index)
            return redirect(url_for("transactions.transactions_page"))
        
        if action == "delay":
            delay_existing_transaction(row_index, request.form.get("delay_date", ""))
            return redirect(request.referrer or url_for("transactions.transactions_page"))

        if action == "update":
            update_existing_transaction(row_index, request.form)
            return redirect(url_for("transactions.transaction_detail", row_index=row_index))

    try:
        tx, categories = transaction_detail_context(row_index)
    except LookupError:
        return f"Transaction {row_index} not found", 404

    return render_template("core/transaction_detail.html", tx=tx, categories=categories, account_options=account_options_for_forms())
