from flask import Blueprint, render_template, request

from money_manager.services.analysis_calculation_service import get_yearly_summary_cached

bp = Blueprint("yearly_summary", __name__)


@bp.route("/yearly-summary")
def yearly_summary_page():
    return render_template(
        "core/yearly_summary.html",
        **get_yearly_summary_cached(request.args.get("year")),
    )
