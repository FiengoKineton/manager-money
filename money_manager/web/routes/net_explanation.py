from flask import Blueprint, render_template, request

from money_manager.services.net_explanation_service import build_net_explanation_context

bp = Blueprint("net_explanation", __name__)


@bp.route("/net-explanation")
def net_explanation():
    from money_manager.web.context import resolve_request_scope, scope_template_context

    selected_scope = resolve_request_scope(request)
    context = build_net_explanation_context(scope=selected_scope["scope"])
    context.update(scope_template_context(selected_scope))
    return render_template("core/net_explanation.html", **context)
