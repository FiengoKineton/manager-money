from flask import Blueprint, render_template, request

from money_manager.services.yearly_summary_service import build_yearly_summary_context

bp = Blueprint("yearly_summary", __name__)


@bp.route("/yearly-summary")
def yearly_summary_page():
    return render_template(
        "core/yearly_summary.html",
        **build_yearly_summary_context(request.args.get("year")),
    )
