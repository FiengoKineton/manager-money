from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, url_for

from money_manager.services.discount_balance_service import (
    archive_discount_source,
    create_discount_source_from_form,
    discount_balances_page_context,
    update_discount_source_from_form,
)

bp = Blueprint("discount_balances", __name__)


@bp.route("/discount-balances", methods=["GET", "POST"])
def discount_balances_page():
    message = request.args.get("message", "")
    error = request.args.get("error", "")

    if request.method == "POST":
        action = str(request.form.get("action") or "").strip()
        source_id = str(request.form.get("source_id") or "").strip()

        if action == "create":
            result = create_discount_source_from_form(request.form)
        elif action == "update":
            result = update_discount_source_from_form(source_id, request.form)
        elif action == "archive":
            result = archive_discount_source(source_id, archived=True)
        elif action == "restore":
            result = archive_discount_source(source_id, archived=False)
        else:
            result = {"ok": False, "error": "Unknown action."}

        query_key = "message" if result.get("ok") else "error"
        query_value = result.get("message") if result.get("ok") else result.get("error", "The balance was not saved.")
        return redirect(url_for("discount_balances.discount_balances_page", **{query_key: query_value}))

    return render_template(
        "support/discount_balances.html",
        message=message,
        error=error,
        **discount_balances_page_context(),
    )
