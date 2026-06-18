from flask import Blueprint, render_template, request

from money_manager.services.analytics_service import build_analysis_metrics
from money_manager.services.transaction_service import load_transactions

bp = Blueprint("analysis", __name__)


@bp.route("/analysis")
def analysis():
    period_key = request.args.get("period", "ytd")
    metrics = build_analysis_metrics(load_transactions(), period_key=period_key)
    return render_template("core/analysis.html", **metrics)
