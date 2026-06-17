from flask import Blueprint, render_template

from money_manager.services.net_explanation_service import build_net_explanation_context

bp = Blueprint("net_explanation", __name__)


@bp.route("/net-explanation")
def net_explanation():
    return render_template("core/net_explanation.html", **build_net_explanation_context())
