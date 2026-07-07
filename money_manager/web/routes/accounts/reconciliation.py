from flask import Blueprint, redirect, render_template, request, url_for

from money_manager.services.account_reconciliation_service import reconciliation_context, update_reconciliation_from_form

bp = Blueprint("reconciliation", __name__, url_prefix="/reconciliation")


@bp.route("", methods=["GET", "POST"])
def reconciliation_page():
    if request.method == "POST":
        update_reconciliation_from_form(request.form)
        return redirect(url_for("reconciliation.reconciliation_page"))
    return render_template("accounts/reconciliation.html", **reconciliation_context())
