from datetime import date

from flask import Blueprint, redirect, render_template, request, url_for

from money_manager.config import TRANSACTION_TYPES
from money_manager.domain.transaction import TransactionInput
from money_manager.services.category_service import category_context
from money_manager.services.transaction_service import (
    delete_existing_transaction,
    save_new_transaction,
    transaction_detail_context,
    update_existing_transaction,
)

bp = Blueprint("transactions", __name__)


@bp.route("/add", methods=["GET", "POST"])
def add_transaction():
    if request.method == "POST":
        save_new_transaction(TransactionInput.from_form(request.form))
        return redirect(url_for("dashboard.index"))

    transaction_type = request.args.get("type", "expense")
    if transaction_type not in TRANSACTION_TYPES:
        transaction_type = "expense"

    context = category_context(transaction_type)
    return render_template(
        "add_transaction.html",
        **context,
        today=date.today().isoformat(),
    )


@bp.route("/transaction/<int:row_index>", methods=["GET", "POST"])
def transaction_detail(row_index: int):
    if request.method == "POST":
        action = request.form.get("action")

        if action == "delete":
            delete_existing_transaction(row_index)
            return redirect(url_for("dashboard.index"))

        if action == "update":
            update_existing_transaction(row_index, request.form)
            return redirect(url_for("transactions.transaction_detail", row_index=row_index))

    try:
        tx, categories = transaction_detail_context(row_index)
    except LookupError:
        return f"Transaction {row_index} not found", 404

    return render_template("transaction_detail.html", tx=tx, categories=categories)
