from __future__ import annotations

from pathlib import Path

from flask import Blueprint, redirect, request, send_file, url_for
from werkzeug.utils import secure_filename

from money_manager.services.backup_service import (
    BackupValidationError,
    export_current_user_backup,
    restore_current_user_backup,
)
from money_manager.web.auth import login_required

bp = Blueprint("backup", __name__, url_prefix="/backup")


@bp.get("/export")
@login_required
def export_backup():
    path = export_current_user_backup()
    return send_file(
        path,
        mimetype="application/zip",
        as_attachment=True,
        download_name=path.name,
        conditional=True,
        max_age=0,
    )


@bp.post("/import")
@login_required
def import_backup():
    upload = request.files.get("backup_zip")
    if not upload or not upload.filename:
        return redirect(url_for("profile.profile_page", error="backup_missing") + "#backup")
    filename = secure_filename(upload.filename or "backup.zip")
    if Path(filename).suffix.lower() != ".zip":
        return redirect(url_for("profile.profile_page", error="backup_type") + "#backup")

    mode = str(request.form.get("import_mode") or "replace").strip().casefold()
    try:
        result = restore_current_user_backup(upload.stream, mode=mode)
    except BackupValidationError:
        return redirect(url_for("profile.profile_page", error="backup_invalid") + "#backup")
    except Exception:
        return redirect(url_for("profile.profile_page", error="backup_restore_failed") + "#backup")

    restored = int(result.get("restored_files") or 0)
    return redirect(url_for("profile.profile_page", saved="backup_imported", restored=restored) + "#backup")
