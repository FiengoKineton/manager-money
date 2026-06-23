from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, url_for

from money_manager.services.account_integrity_service import full_integrity_report, rebuild_ledger_preview, repair_safe

bp = Blueprint("integrity", __name__, url_prefix="/settings/integrity")


@bp.get("")
def integrity_page():
    report = full_integrity_report()
    preview = rebuild_ledger_preview()
    repair_result = None
    return render_template("profile/integrity.html", report=report, preview=preview, repair_result=repair_result)


@bp.post("/rebuild-ledger-preview")
def rebuild_ledger_preview_route():
    report = full_integrity_report()
    preview = rebuild_ledger_preview()
    return render_template("profile/integrity.html", report=report, preview=preview, repair_result=None)


@bp.post("/repair-safe")
def repair_safe_route():
    confirmed = str(request.form.get("confirm") or "").strip().casefold() in {"1", "true", "yes", "on"}
    result = repair_safe(confirm=confirmed)
    report = result.get("report") if isinstance(result.get("report"), dict) else full_integrity_report()
    preview = rebuild_ledger_preview()
    return render_template("profile/integrity.html", report=report, preview=preview, repair_result=result)
