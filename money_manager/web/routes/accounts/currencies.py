from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from money_manager.services.currency_service import (
    add_currency_from_form,
    fetch_currency_history,
    page_context,
    refresh_currency_rates,
    update_currency_from_form,
)

bp = Blueprint("currencies", __name__, url_prefix="/currencies")


@bp.route("", methods=["GET", "POST"])
def currencies_page():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "refresh_rates":
            refresh_currency_rates(force=True)
        elif action == "update_currency":
            update_currency_from_form(request.form)
        elif action == "add_currency":
            add_currency_from_form(request.form)
        return redirect(url_for("currencies.currencies_page"))

    return render_template("accounts/currencies.html", **page_context())


@bp.get("/history-data")
def currency_history_data():
    codes = request.args.get("codes", "")
    period = request.args.get("period", "90d")
    group = request.args.get("group", "auto")
    return jsonify(fetch_currency_history(codes, period=period, group=group))
