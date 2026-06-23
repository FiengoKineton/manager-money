from flask import Blueprint, render_template, request

from money_manager.services.analytics_service import build_analysis_metrics
from money_manager.services.transaction_service import load_transactions
from money_manager.services.calculation_service import cached_context
from money_manager.web.context import resolve_request_scope, scope_template_context

bp = Blueprint("analysis", __name__)


@bp.route("/analysis")
def analysis():
    period_key = request.args.get("period", "ytd")
    selected_scope = resolve_request_scope(request)
    scope_key = selected_scope["scope"]
    metrics = cached_context(
        "analysis_metrics",
        lambda: build_analysis_metrics(load_transactions(), period_key=period_key, scope=scope_key),
        params={"period": period_key, "scope": scope_key},
    )
    context = dict(metrics)
    context.update(scope_template_context(selected_scope))
    return render_template("core/analysis.html", **context)