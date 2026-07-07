from __future__ import annotations

from datetime import date

from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from money_manager.services.bonifico_service import bonifico_form_context, record_bonifico
from money_manager.services.category_service import category_context
from money_manager.services.contact_service import contact_views, search_contacts
from money_manager.services.preferences_service import load_preferences
from money_manager.web.auth import login_required

bp = Blueprint("bonifico", __name__)


@bp.route("/bonifico", methods=["GET", "POST"])
@login_required
def bonifico_page():
    preferences = load_preferences()
    show_sensitive_data = bool(preferences.get("show_sensitive_data", False))
    contacts = search_contacts("")
    status = None
    form_values: dict = {}
    errors: list[str] = []

    if request.method == "POST":
        form_values = request.form.to_dict()
        result = record_bonifico(request.form)
        if result.get("ok"):
            if result.get("created_contact"):
                saved = "recorded_created_contact"
            elif result.get("target_type") in {"debt", "debts"}:
                saved = "recorded_debt"
            elif result.get("target_type") == "payable":
                saved = "recorded_payable"
            else:
                saved = "recorded"
            return redirect(url_for("bonifico.bonifico_page", saved=saved))
        errors = result.get("errors") or [result.get("error") or "Bonifico was not recorded."]
        status = {"tone": "error", "messages": errors}
    else:
        saved = str(request.args.get("saved") or "")
        if saved == "recorded_created_contact":
            status = {"tone": "success", "keys": ["bonifico.status_recorded_created_contact"]}
        elif saved == "recorded_debt":
            status = {"tone": "success", "keys": ["bonifico.status_recorded_debt"]}
        elif saved == "recorded_payable":
            status = {"tone": "success", "keys": ["bonifico.status_recorded_payable"]}
        elif saved == "recorded":
            status = {"tone": "success", "keys": ["bonifico.status_recorded"]}

    context = category_context("expense")
    context.update(bonifico_form_context())
    return render_template(
        "bonifico/bonifico.html",
        **context,
        contacts=contact_views(contacts, show_sensitive_data=show_sensitive_data),
        contacts_json=contact_views(contacts, show_sensitive_data=show_sensitive_data),
        today=date.today().isoformat(),
        show_sensitive_data=show_sensitive_data,
        form_values=form_values,
        errors=errors,
        status=status,
    )


@bp.get("/api/contacts/search")
@login_required
def contacts_search_api():
    query = str(request.args.get("q") or "").strip()
    preferences = load_preferences()
    show_sensitive_data = bool(preferences.get("show_sensitive_data", False))
    contacts = contact_views(search_contacts(query), show_sensitive_data=show_sensitive_data)
    return jsonify(
        {
            "items": [
                {
                    "id": contact.get("id", ""),
                    "display_name": contact.get("display_name", ""),
                    "type": contact.get("type", ""),
                    "iban_display": contact.get("iban_list_value", ""),
                    "bic_swift": contact.get("bic_swift", ""),
                    "bank_name": contact.get("bank_name", ""),
                    "has_bank_details": bool(contact.get("has_bank_details")),
                }
                for contact in contacts[:20]
            ]
        }
    )
