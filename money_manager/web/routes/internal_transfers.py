from flask import Blueprint, redirect, render_template, request, url_for

from money_manager.services.internal_transfer_service import (
    create_transfer,
    delete_transfer_from_form,
    page_context,
    update_transfer_from_form,
)

bp = Blueprint("internal_transfers", __name__, url_prefix="/internal-transfers")


@bp.route("", methods=["GET", "POST"])
def internal_transfers_page():
    error = ""
    message = request.args.get("message", "")

    if request.method == "POST":
        action = request.form.get("action", "")
        if action == "add_transfer":
            result = create_transfer(request.form)
        elif action == "update_transfer":
            result = update_transfer_from_form(request.form)
        elif action == "delete_transfer":
            result = delete_transfer_from_form(request.form)
        else:
            result = {"ok": False, "error": "Unknown transfer action."}

        if result.get("ok"):
            return redirect(url_for("internal_transfers.internal_transfers_page", message=result.get("message", "Saved.")))
        error = result.get("error", "Transfer was not saved.")

    return render_template("internal_transfers.html", **page_context(error=error, message=message))
