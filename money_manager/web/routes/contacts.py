from __future__ import annotations

from flask import Blueprint, abort, redirect, render_template, request, url_for

from money_manager.services.contact_service import (
    add_contact,
    archive_contact,
    contact_counts,
    contact_view,
    contact_views,
    duplicate_warnings,
    get_contact,
    prepare_contact_for_form,
    restore_contact,
    search_contacts,
    update_contact,
)
from money_manager.services.preferences_service import load_preferences
from money_manager.utils.privacy import should_mask_sensitive
from money_manager.web.auth import login_required

bp = Blueprint("contacts", __name__, url_prefix="/contacts")


@bp.get("")
@login_required
def contacts_page():
    query = str(request.args.get("q") or "").strip()
    include_archived = request.args.get("archived") in {"1", "true", "yes", "on"}
    preferences = load_preferences()
    show_sensitive_data = not should_mask_sensitive(preferences)
    contacts = search_contacts(query, include_archived=include_archived)
    return render_template(
        "contacts/contacts.html",
        contacts=contact_views(contacts, show_sensitive_data=show_sensitive_data),
        query=query,
        include_archived=include_archived,
        counts=contact_counts(),
        show_sensitive_data=show_sensitive_data,
        status=_status_message(request.args.get("saved"), request.args.get("warning")),
    )


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new_contact():
    if request.method == "POST":
        form_data = _contact_payload_from_form()
        warnings = duplicate_warnings(form_data)
        contact = add_contact(form_data)
        return redirect(
            url_for(
                "contacts.contact_detail",
                contact_id=contact["id"],
                saved="created",
                warning=_warning_query(warnings),
            )
        )

    return render_template(
        "contacts/contact_form.html",
        contact=prepare_contact_for_form({"type": request.args.get("type") or "person"}),
        mode="new",
        action_url=url_for("contacts.new_contact"),
        status=None,
    )


@bp.route("/<contact_id>", methods=["GET", "POST"])
@login_required
def contact_detail(contact_id: str):
    contact = get_contact(contact_id)
    if contact is None:
        abort(404)

    if request.method == "POST":
        form_data = _contact_payload_from_form()
        warnings = duplicate_warnings(form_data, exclude_id=contact_id)
        updated = update_contact(contact_id, form_data)
        return redirect(
            url_for(
                "contacts.contact_detail",
                contact_id=updated["id"],
                saved="updated",
                warning=_warning_query(warnings),
            )
        )

    preferences = load_preferences()
    show_sensitive_data = not should_mask_sensitive(preferences)
    return render_template(
        "contacts/contact_detail.html",
        contact=contact_view(contact, show_sensitive_data=show_sensitive_data),
        show_sensitive_data=show_sensitive_data,
        status=_status_message(request.args.get("saved"), request.args.get("warning")),
    )


@bp.get("/<contact_id>/edit")
@login_required
def edit_contact(contact_id: str):
    contact = get_contact(contact_id)
    if contact is None:
        abort(404)
    return render_template(
        "contacts/contact_form.html",
        contact=prepare_contact_for_form(contact),
        mode="edit",
        action_url=url_for("contacts.contact_detail", contact_id=contact_id),
        status=_status_message(request.args.get("saved"), request.args.get("warning")),
    )


@bp.post("/<contact_id>/archive")
@login_required
def archive_contact_route(contact_id: str):
    if get_contact(contact_id) is None:
        abort(404)
    archive_contact(contact_id)
    return redirect(url_for("contacts.contacts_page", saved="archived"))


@bp.post("/<contact_id>/restore")
@login_required
def restore_contact_route(contact_id: str):
    if get_contact(contact_id) is None:
        abort(404)
    restore_contact(contact_id)
    return redirect(url_for("contacts.contact_detail", contact_id=contact_id, saved="restored"))


def _contact_payload_from_form() -> dict:
    contact_type = str(request.form.get("type") or "person").strip().casefold()
    return {
        "type": contact_type if contact_type in {"person", "company"} else "person",
        "first_name": request.form.get("first_name", ""),
        "last_name": request.form.get("last_name", ""),
        "company_name": request.form.get("company_name", ""),
        "display_name": request.form.get("display_name", ""),
        "relationship": request.form.get("relationship", ""),
        "iban": request.form.get("iban", ""),
        "bic_swift": request.form.get("bic_swift", ""),
        "bank_name": request.form.get("bank_name", ""),
        "email": request.form.get("email", ""),
        "phone": request.form.get("phone", ""),
        "vat_number": request.form.get("vat_number", ""),
        "fiscal_code": request.form.get("fiscal_code", ""),
        "pec_email": request.form.get("pec_email", ""),
        "sdi_code": request.form.get("sdi_code", ""),
        "registered_address": request.form.get("registered_address", ""),
        "city": request.form.get("city", ""),
        "province": request.form.get("province", ""),
        "postal_code": request.form.get("postal_code", ""),
        "country": request.form.get("country", ""),
        "notes": request.form.get("notes", ""),
    }


def _warning_query(warnings: list[str]) -> str:
    return ",".join(code for code in warnings if code in {"duplicate_name", "duplicate_iban"})


def _status_message(saved: str | None, warning: str | None) -> dict | None:
    saved_keys = {
        "created": "contacts.status_created",
        "updated": "contacts.status_updated",
        "archived": "contacts.status_archived",
        "restored": "contacts.status_restored",
    }
    warning_codes = {code for code in str(warning or "").split(",") if code}
    warning_keys = []
    if "duplicate_name" in warning_codes:
        warning_keys.append("contacts.warning_duplicate_name")
    if "duplicate_iban" in warning_codes:
        warning_keys.append("contacts.warning_duplicate_iban")
    if warning_keys:
        return {"tone": "warning", "keys": warning_keys, "saved_key": saved_keys.get(str(saved or ""))}
    key = saved_keys.get(str(saved or ""))
    if key:
        return {"tone": "success", "keys": [key], "saved_key": None}
    return None
