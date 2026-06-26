from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, url_for

from money_manager.services.mortgage_service import (
    archive_mortgage,
    create_mortgage_from_form,
    delete_mortgage,
    mortgages_page_context,
    update_mortgage_from_form,
)
from money_manager.web.auth import login_required

bp = Blueprint("mortgages", __name__)


@bp.route("/mortgages", methods=["GET", "POST"])
@login_required
def mortgages_page():
    if request.method == "POST":
        action = str(request.form.get("action") or "").strip()
        mortgage_id = str(request.form.get("mortgage_id") or "").strip()
        if action == "create":
            result = create_mortgage_from_form(request.form)
        elif action == "update":
            result = update_mortgage_from_form(mortgage_id, request.form)
        elif action == "archive":
            result = archive_mortgage(mortgage_id, archived=True)
        elif action == "restore":
            result = archive_mortgage(mortgage_id, archived=False)
        elif action == "delete":
            result = delete_mortgage(mortgage_id)
        else:
            result = {"ok": False, "error": "Unknown action."}

        query_key = "message" if result.get("ok") else "error"
        query_value = result.get("message") if result.get("ok") else result.get("error", "Not saved.")
        return redirect(url_for("mortgages.mortgages_page", **{query_key: query_value}))

    return render_template(
        "planning/mortgages.html",
        **mortgages_page_context(
            message=request.args.get("message", ""),
            error=request.args.get("error", ""),
        ),
    )
