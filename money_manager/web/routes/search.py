from __future__ import annotations

from flask import Blueprint, render_template, request

from money_manager.services.search_service import search_everything
from money_manager.web.auth import login_required

bp = Blueprint("search", __name__)


@bp.get("/search")
@login_required
def search_page():
    q = request.args.get("q", "")
    context = search_everything(q)
    return render_template("search.html", **context)
