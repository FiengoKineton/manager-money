from flask import Blueprint, Response, abort, redirect, render_template, request, url_for

from money_manager.services.payable_detail_service import read_payable_file, save_items_from_form, save_uploaded_files
from money_manager.services.payable_service import (
    add_payable_from_form,
    delete_payable_from_form,
    duplicate_payable_from_form,
    page_context,
    pay_payable_from_form,
    update_payable_from_form,
)
from money_manager.web.context import resolve_request_scope, scope_template_context

bp = Blueprint("payables", __name__, url_prefix="/payables")


@bp.route("", methods=["GET", "POST"])
def payables_page():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add_payable":
            add_payable_from_form(request.form)
        elif action == "pay_payable":
            pay_payable_from_form(request.form)
        elif action == "delete_payable":
            delete_payable_from_form(request.form)
        elif action == "update_payable":
            update_payable_from_form(request.form)
        elif action == "duplicate_payable":
            duplicate_payable_from_form(request.form)
        elif action == "save_payable_items":
            save_items_from_form(request.form.get("id"), request.form)
        upload_status = ""
        upload_payable_id = ""
        if action == "upload_payable_files":
            upload_payable_id = str(request.form.get("id") or "")
            result = save_uploaded_files(upload_payable_id, request.files.getlist("payable_files"))
            if result.get("saved") and not result.get("errors"):
                upload_status = "uploaded"
            elif result.get("saved"):
                upload_status = "partial"
            else:
                upload_status = "failed"
        account_id = request.args.get("account_id", "")
        target = url_for("payables.payables_page", account_id=account_id) if account_id else url_for("payables.payables_page")
        if upload_status:
            separator = "&" if "?" in target else "?"
            target = f"{target}{separator}upload={upload_status}&payable_id={upload_payable_id}"
        return redirect(target)

    selected_scope = resolve_request_scope(request)
    context = page_context(scope=selected_scope)
    context.update(scope_template_context(selected_scope))
    context["upload_status"] = str(request.args.get("upload") or "")
    context["upload_payable_id"] = str(request.args.get("payable_id") or "")
    return render_template("planning/payables.html", **context)

@bp.get("/<int:payable_id>/files/<path:stored_name>")
def payable_file(payable_id: int, stored_name: str):
    result = read_payable_file(payable_id, stored_name)
    if not result:
        abort(404)
    data, metadata = result
    return Response(data, mimetype=metadata.get("mime_type") or "application/octet-stream", headers={"Content-Disposition": f'inline; filename="{metadata.get("display_name") or stored_name}"'})
