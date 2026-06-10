from flask import Blueprint, redirect, render_template, request, url_for

from money_manager.services.investment_service import (
    add_asset_from_form,
    delete_asset_from_form,
    page_context,
    refresh_market_data,
    update_asset_from_form,
)

bp = Blueprint("investments", __name__, url_prefix="/investments")


@bp.route("", methods=["GET", "POST"])
def investments_page():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add_asset":
            add_asset_from_form(request.form)
        elif action == "delete_asset":
            delete_asset_from_form(request.form)
        elif action == "update_asset":
            update_asset_from_form(request.form)
        elif action == "refresh_market":
            refresh_market_data(force=True)
        return redirect(url_for("investments.investments_page"))

    return render_template("investments.html", **page_context())
