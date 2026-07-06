from __future__ import annotations

from pathlib import Path

from flask import Blueprint, abort, redirect, render_template, request, send_file, session, url_for

from money_manager.security.decrypted_export_service import (
    active_exports_for_user,
    cancel_decrypted_export,
    cleanup_expired_decrypted_exports,
    create_decrypted_export,
    get_decrypted_export,
    mark_decrypted_export_downloaded,
)
from money_manager.security.encryption_migration_service import EncryptionMigrationError, dry_run_encryption, enable_encryption_for_user, migrate_user_to_encrypted_storage
from money_manager.security.encryption_policy import TEMP_EXPORT_TTL_MINUTES
from money_manager.security.key_manager import UnlockFailed, is_encryption_enabled, rewrap_dek
from money_manager.security.security_audit_service import security_audit, verify_user_encryption
from money_manager.security.session_vault import is_unlocked, lock_vault, unlock_user, vault_status
from money_manager.cache.precompute_service import warm_cache_on_login
from money_manager.users.user_manager import authenticate_user, update_user_password
from money_manager.web.auth import login_required

bp = Blueprint("security", __name__)


@bp.route("/security/unlock", methods=["GET", "POST"])
def unlock():
    user_id = str(session.get("user_id") or "")
    if not user_id:
        return redirect(url_for("auth.login", next=request.args.get("next") or url_for("dashboard.index")))
    next_url = request.args.get("next") or request.form.get("next") or url_for("dashboard.index")
    if not is_encryption_enabled(user_id):
        return redirect(next_url)
    error = None
    if request.method == "POST":
        password = request.form.get("password", "")
        try:
            unlock_user(user_id, password)
        except Exception:
            error = "Wrong password or corrupted vault metadata."
        else:
            try:
                warm_cache_on_login(user_id)
            except Exception:
                pass
            return redirect(next_url)
    return render_template("settings/unlock.html", error=error, next_url=next_url, unlock_username=session.get("display_name") or session.get("username") or "Local user")


@bp.post("/security/lock")
@login_required
def lock():
    lock_vault()
    return redirect(url_for("security.unlock", next=request.form.get("next") or url_for("security.security_page")))


@bp.get("/settings/security")
@login_required
def security_page():
    cleanup_expired_decrypted_exports()
    user_id = str(session.get("user_id") or "")
    audit = security_audit(user_id)
    dry_run = dry_run_encryption(user_id)
    return render_template(
        "settings/security.html",
        audit=audit,
        verification=audit.get("verification") or verify_user_encryption(user_id),
        dry_run=dry_run,
        vault=vault_status(user_id),
        decrypted_exports=active_exports_for_user(user_id),
        temp_export_ttl_minutes=TEMP_EXPORT_TTL_MINUTES,
        saved=request.args.get("saved", ""),
        error=request.args.get("error", ""),
    )


@bp.post("/security/scan")
@login_required
def scan_encryption():
    # The page itself performs a real scan; this route exists for the explicit button.
    return redirect(url_for("security.security_page", saved="scan_complete"))


@bp.post("/security/enable")
@login_required
def enable_encryption():
    user_id = str(session.get("user_id") or "")
    password = request.form.get("password", "")
    username = str(session.get("username") or "")
    if not authenticate_user(username, password):
        return redirect(url_for("security.security_page", error="wrong_password"))
    try:
        result = enable_encryption_for_user(user_id, password, create_backup=True)
    except EncryptionMigrationError:
        return redirect(url_for("security.security_page", error="migration_failed"))
    except Exception:
        return redirect(url_for("security.security_page", error="enable_failed"))
    return redirect(url_for("security.security_page", saved=f"enabled_{result.get('encrypted_files', 0)}"))


@bp.post("/security/migrate")
@login_required
def migrate_encryption():
    user_id = str(session.get("user_id") or "")
    username = str(session.get("username") or "")
    password = request.form.get("password", "")
    if not authenticate_user(username, password):
        return redirect(url_for("security.security_page", error="wrong_password"))
    try:
        report = migrate_user_to_encrypted_storage(user_id, password)
    except Exception:
        return redirect(url_for("security.security_page", error="migration_failed"))
    if not report.get("success"):
        return redirect(url_for("security.security_page", error="plaintext_remaining"))
    return redirect(url_for("security.security_page", saved=f"migrated_{report.get('files_encrypted', 0)}"))


@bp.post("/security/change-password")
@login_required
def change_password():
    user_id = str(session.get("user_id") or "")
    username = str(session.get("username") or "")
    old_password = request.form.get("old_password", "")
    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")
    if not new_password or new_password != confirm_password:
        return redirect(url_for("security.security_page", error="password_mismatch"))
    if not authenticate_user(username, old_password):
        return redirect(url_for("security.security_page", error="wrong_password"))
    try:
        if is_encryption_enabled(user_id):
            rewrap_dek(user_id, old_password, new_password)
        update_user_password(user_id, new_password)
        if is_encryption_enabled(user_id):
            unlock_user(user_id, new_password)
    except UnlockFailed:
        return redirect(url_for("security.security_page", error="rewrap_failed"))
    except Exception:
        return redirect(url_for("security.security_page", error="password_change_failed"))
    return redirect(url_for("security.security_page", saved="password_changed"))


@bp.get("/settings/security/export-decrypted")
@login_required
def export_decrypted_page():
    cleanup_expired_decrypted_exports()
    user_id = str(session.get("user_id") or "")
    return render_template(
        "settings/export_decrypted.html",
        exports=active_exports_for_user(user_id),
        ttl_minutes=TEMP_EXPORT_TTL_MINUTES,
        error=request.args.get("error", ""),
        saved=request.args.get("saved", ""),
    )


@bp.post("/settings/security/export-decrypted/start")
@login_required
def export_decrypted_start():
    user_id = str(session.get("user_id") or "")
    username = str(session.get("username") or "")
    password = request.form.get("password", "")
    if not authenticate_user(username, password):
        return redirect(url_for("security.export_decrypted_page", error="wrong_password"))
    try:
        created = create_decrypted_export(user_id, password)
    except Exception:
        return redirect(url_for("security.export_decrypted_page", error="export_failed"))
    return redirect(url_for("security.export_decrypted_page", saved=f"export_ready_{created.get('export_id', '')}"))


@bp.get("/settings/security/export-decrypted/download/<export_id>")
@login_required
def export_decrypted_download(export_id: str):
    user_id = str(session.get("user_id") or "")
    try:
        metadata = get_decrypted_export(user_id, export_id)
        zip_path = Path(metadata["zip_path"])
    except Exception:
        abort(404)
    mark_decrypted_export_downloaded(user_id, export_id)
    return send_file(
        zip_path,
        mimetype="application/zip",
        as_attachment=True,
        download_name="user_data_decrypted.zip",
        conditional=True,
        max_age=0,
    )


@bp.post("/settings/security/export-decrypted/cancel/<export_id>")
@login_required
def export_decrypted_cancel(export_id: str):
    user_id = str(session.get("user_id") or "")
    try:
        cancel_decrypted_export(user_id, export_id)
    except Exception:
        return redirect(url_for("security.export_decrypted_page", error="cancel_failed"))
    return redirect(url_for("security.export_decrypted_page", saved="export_cancelled"))
