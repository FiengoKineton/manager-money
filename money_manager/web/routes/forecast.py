from flask import Blueprint, render_template, request

from money_manager.services.forecast_service import project_wealth

bp = Blueprint("forecast", __name__)


@bp.route("/forecast", methods=["GET", "POST"])
def forecast():
    result = None

    if request.method == "POST":
        monthly_income = float(request.form.get("income", 0))
        monthly_expenses = float(request.form.get("expenses", 0))
        monthly_investment = float(request.form.get("investment", 0))
        years = int(request.form.get("years", 5))
        annual_rate = float(request.form.get("rate", 5)) / 100.0

        result = project_wealth(
            monthly_income=monthly_income,
            monthly_expenses=monthly_expenses,
            monthly_investment=monthly_investment,
            years=years,
            annual_rate=annual_rate,
        )

    return render_template("forecast.html", result=result)
