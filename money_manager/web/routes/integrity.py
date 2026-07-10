from __future__ import annotations

from flask import Blueprint, render_template, request

from money_manager.services.account_integrity_service import full_integrity_report, rebuild_ledger_preview, repair_safe
from money_manager.services.movement_history_service import movement_history_status, refresh_movement_histories

bp = Blueprint("integrity", __name__, url_prefix="/settings/integrity")


def _render(*, repair_result=None, movement_history_result=None):
    report = (
        repair_result.get("report")
        if isinstance(repair_result, dict) and isinstance(repair_result.get("report"), dict)
        else full_integrity_report()
    )
    return render_template(
        "profile/integrity.html",
        report=report,
        preview=rebuild_ledger_preview(),
        repair_result=repair_result,
        movement_history=movement_history_status(),
        movement_history_result=movement_history_result,
    )


@bp.get("")
def integrity_page():
    return _render()


@bp.post("/rebuild-ledger-preview")
def rebuild_ledger_preview_route():
    return _render()


@bp.post("/repair-safe")
def repair_safe_route():
    confirmed = str(request.form.get("confirm") or "").strip().casefold() in {"1", "true", "yes", "on"}
    return _render(repair_result=repair_safe(confirm=confirmed))


@bp.post("/refresh-movement-histories")
def refresh_movement_histories_route():
    confirmed = str(request.form.get("confirm") or "").strip().casefold() in {"1", "true", "yes", "on"}
    result = refresh_movement_histories(confirm=confirmed)
    return _render(movement_history_result=result)
