from flask import Blueprint, redirect, render_template, request, url_for

from money_manager.services.currency_service import (
    add_currency_from_form,
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
