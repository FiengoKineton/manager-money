from flask import Blueprint, render_template, request

from money_manager.services.forecast_service import build_forecast_page_context

bp = Blueprint("forecast", __name__)


@bp.route("/forecast", methods=["GET", "POST"])
def forecast():
    context = build_forecast_page_context(request.form if request.method == "POST" else None)
    return render_template("planning/forecast.html", **context)
