from datetime import date
import json

from flask import Blueprint, redirect, render_template, request, url_for

from money_manager.config import TRANSACTION_TYPES, account_options_for_forms, default_date_range
from money_manager.domain.transaction import TransactionInput
from money_manager.services.account_service import main_account_transactions
from money_manager.services.analytics_service import apply_transaction_filters
from money_manager.services.category_service import category_context
from money_manager.services.currency_service import currency_options_for_forms
from money_manager.services.transaction_service import (
    delete_existing_transaction,
    load_transactions,
    prepare_transactions_for_display,
    save_new_transaction,
    transaction_detail_context,
    update_existing_transaction,
)

bp = Blueprint("transactions", __name__)


@bp.route("/transactions")
def transactions_page():
    df = load_transactions()
    main_df = main_account_transactions(df)

    start_default, end_default = default_date_range()
    start = request.args.get("from", start_default)
    end = request.args.get("to", end_default)

    types = request.args.getlist("types") or TRANSACTION_TYPES[:]
    categories = request.args.getlist("category")
    query = request.args.get("q", "").strip()
    amount_min = request.args.get("amount_min", "").strip()
    amount_max = request.args.get("amount_max", "").strip()

    filtered = apply_transaction_filters(df, start, end, types, categories, query, amount_min, amount_max)
    filtered = prepare_transactions_for_display(filtered)
    all_categories = sorted(main_df["category"].dropna().unique().tolist()) if not main_df.empty else []

    return render_template(
        "transactions.html",
        transactions=filtered.to_dict(orient="records"),
        transactions_initial=filtered.head(50).to_dict(orient="records"),
        start=start,
        end=end,
        active_types=types,
        all_types=TRANSACTION_TYPES,
        categories_selected=categories,
        categories_all=all_categories,
        q=query,
        amount_min=amount_min,
        amount_max=amount_max,
    )


@bp.route("/add", methods=["GET", "POST"])
def add_transaction():
    if request.method == "POST":
        save_new_transaction(TransactionInput.from_form(request.form))
        return redirect(url_for("transactions.transactions_page"))

    transaction_type = request.args.get("type", "expense")
    if transaction_type not in TRANSACTION_TYPES:
        transaction_type = "expense"

    context = category_context(transaction_type)
    currency_options = currency_options_for_forms()
    return render_template(
        "add_transaction.html",
        **context,
        today=date.today().isoformat(),
        currency_options=currency_options,
        currency_options_json=json.dumps(currency_options),
    )


@bp.route("/transaction/<int:row_index>", methods=["GET", "POST"])
def transaction_detail(row_index: int):
    if request.method == "POST":
        action = request.form.get("action")

        if action == "delete":
            delete_existing_transaction(row_index)
            return redirect(url_for("transactions.transactions_page"))

        if action == "update":
            update_existing_transaction(row_index, request.form)
            return redirect(url_for("transactions.transaction_detail", row_index=row_index))

    try:
        tx, categories = transaction_detail_context(row_index)
    except LookupError:
        return f"Transaction {row_index} not found", 404

    return render_template("transaction_detail.html", tx=tx, categories=categories, account_options=account_options_for_forms())
