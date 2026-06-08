from flask import Blueprint, render_template

from money_manager.services.analytics_service import build_analysis_metrics
from money_manager.services.transaction_service import load_transactions

bp = Blueprint("analysis", __name__)


@bp.route("/analysis")
def analysis():
    df = load_transactions()
    metrics = build_analysis_metrics(df)
    return render_template("analysis.html", **metrics)
