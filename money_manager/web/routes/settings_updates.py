from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, url_for

from money_manager.config.user_paths import get_current_user_id
from money_manager.services.update_service import (
    UpdateValidationError,
    list_update_packages,
    request_rollback,
    stage_update_package,
    update_status,
)
from money_manager.storage.data_file_service import data_registry_diagnostics

bp = Blueprint("settings_updates", __name__, url_prefix="/settings")


@bp.get("/updates")
def updates_page():
    return render_template(
        "settings/updates.html",
        status=update_status(),
        packages=list_update_packages(),
        action_result=None,
        error=None,
    )


@bp.post("/updates/stage")
def stage_update_route():
    package = request.form.get("package", "")
    action_result = None
    error = None
    try:
        action_result = stage_update_package(package)
    except UpdateValidationError as exc:
        error = str(exc)
    return render_template(
        "settings/updates.html",
        status=update_status(),
        packages=list_update_packages(),
        action_result=action_result,
        error=error,
    )


@bp.post("/updates/rollback")
def rollback_route():
    action_result = None
    error = None
    try:
        action_result = request_rollback()
    except UpdateValidationError as exc:
        error = str(exc)
    return render_template(
        "settings/updates.html",
        status=update_status(),
        packages=list_update_packages(),
        action_result=action_result,
        error=error,
    )


@bp.get("/data-registry")
def data_registry_page():
    return render_template(
        "settings/data_registry.html",
        rows=data_registry_diagnostics(user_id=get_current_user_id()),
        status=update_status(),
    )
