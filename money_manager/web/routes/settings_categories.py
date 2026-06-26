from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, url_for

from money_manager.config.categories import CATEGORY_OPTIONS, TRANSACTION_TYPES
from money_manager.services.custom_category_service import (
    add_custom_category,
    default_category_for,
    effective_categories_for,
    hide_category,
    load_categories_config,
    restore_category,
    set_default_category,
)
from money_manager.services.category_icon_service import icon_for_category, set_category_icon

bp = Blueprint("settings_categories", __name__, url_prefix="/settings/categories")


def _redirect(message: str = "", status: str = "ok"):
    args = {}
    if message:
        args["message"] = message
        args["status"] = status
    return redirect(url_for("settings_categories.categories_page", **args))


@bp.get("")
def categories_page():
    config = load_categories_config()
    sections = []
    for transaction_type in TRANSACTION_TYPES:
        section = config.get(transaction_type, {}) if isinstance(config.get(transaction_type), dict) else {}
        active = effective_categories_for(transaction_type)
        hidden_lookup = {str(item).casefold() for item in section.get("hidden", [])}
        default_category = default_category_for(transaction_type)
        base_rows = []
        for name in CATEGORY_OPTIONS.get(transaction_type, []):
            base_rows.append(
                {
                    "name": name,
                    "icon": icon_for_category(name, transaction_type),
                    "kind": "default",
                    "active": str(name).casefold() not in hidden_lookup,
                    "is_default": name == default_category,
                }
            )
        custom_rows = []
        for name in section.get("custom", []):
            custom_rows.append(
                {
                    "name": name,
                    "icon": icon_for_category(name, transaction_type),
                    "kind": "custom",
                    "active": str(name).casefold() not in hidden_lookup,
                    "is_default": name == default_category,
                }
            )
        sections.append(
            {
                "type": transaction_type,
                "title": transaction_type.capitalize(),
                "default_category": default_category,
                "active_count": len(active),
                "base_rows": base_rows,
                "custom_rows": custom_rows,
            }
        )
    return render_template(
        "settings/categories.html",
        sections=sections,
        message=request.args.get("message", ""),
        status=request.args.get("status", "ok"),
    )


@bp.post("/add")
def add_category_route():
    transaction_type = request.form.get("transaction_type", "expense")
    name = request.form.get("name", "")
    icon = request.form.get("icon", "")
    try:
        add_custom_category(transaction_type, name)
        if str(icon or "").strip():
            set_category_icon(name, icon, transaction_type)
    except ValueError as exc:
        return _redirect(str(exc), "error")
    return _redirect(f"Added category: {name.strip()}")


@bp.post("/icon")
def category_icon_route():
    transaction_type = request.form.get("transaction_type", "expense")
    name = request.form.get("name", "")
    icon = request.form.get("icon", "")
    try:
        set_category_icon(name, icon, transaction_type)
    except ValueError as exc:
        return _redirect(str(exc), "error")
    return _redirect(f"Updated icon for: {name.strip()}")


@bp.post("/hide")
def hide_category_route():
    transaction_type = request.form.get("transaction_type", "expense")
    name = request.form.get("name", "")
    try:
        hide_category(transaction_type, name)
    except ValueError as exc:
        return _redirect(str(exc), "error")
    return _redirect(f"Hidden category: {name.strip()}")


@bp.post("/restore")
def restore_category_route():
    transaction_type = request.form.get("transaction_type", "expense")
    name = request.form.get("name", "")
    try:
        restore_category(transaction_type, name)
    except ValueError as exc:
        return _redirect(str(exc), "error")
    return _redirect(f"Restored category: {name.strip()}")


@bp.post("/default")
def default_category_route():
    transaction_type = request.form.get("transaction_type", "expense")
    name = request.form.get("name", "")
    try:
        set_default_category(transaction_type, name)
    except ValueError as exc:
        return _redirect(str(exc), "error")
    return _redirect(f"Default category set: {name.strip()}")
