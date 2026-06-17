from flask import Blueprint, render_template

from money_manager.services.analytics_service import build_analysis_metrics_cached

bp = Blueprint("analysis", __name__)


@bp.route("/analysis")
def analysis():
    metrics = build_analysis_metrics_cached()
    return render_template("analysis.html", **metrics)
