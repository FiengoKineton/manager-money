from __future__ import annotations

import mimetypes
from pathlib import Path

from flask import Blueprint, abort, redirect, render_template, request, send_file, url_for
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from money_manager.config import account_options_for_forms
from money_manager.config.user_paths import get_user_data_dir
from money_manager.services.currency_service import currency_options_for_forms
from money_manager.services.i18n_service import available_language_codes
from money_manager.services.navigation_service import (
    get_effective_navigation,
    hide_page,
    move_page,
    restore_default_navigation,
    set_group_collapsed,
    show_page,
)
from money_manager.services.preferences_service import load_preferences, update_preferences
from money_manager.services.profile_service import (
    display_name_from_profile,
    initials_from_profile,
    load_profile,
    save_profile,
    update_profile,
)
from money_manager.web.auth import current_user

bp = Blueprint("profile", __name__, url_prefix="/profile")

ALLOWED_AVATAR_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
MAX_AVATAR_BYTES = 3 * 1024 * 1024
AVATAR_DIRNAME = "profile"

PROFILE_FIELDS = {
    "first_name",
    "last_name",
    "display_name",
    "birth_year",
    "bank_name",
    "iban",
    "bic_swift",
    "default_main_account",
}
PREFERENCE_FIELDS_FROM_PROFILE = {"currency", "date_format"}
PREFERENCE_FIELDS = {"theme", "language", "privacy_mode", "show_sensitive_data"}
DATE_FORMAT_OPTIONS = [
    {"value": "dd/mm/yyyy", "label": "DD/MM/YYYY"},
    {"value": "yyyy-mm-dd", "label": "YYYY-MM-DD"},
    {"value": "mm/dd/yyyy", "label": "MM/DD/YYYY"},
]
THEME_OPTIONS = [
    {"value": "day", "label": "Day"},
    {"value": "night", "label": "Night"},
]


@bp.route("", methods=["GET", "POST"])
def profile_page():
    if request.method == "POST":
        profile_updates = {field: request.form.get(field, "") for field in PROFILE_FIELDS}
        update_profile(profile_updates)

        preference_updates = {
            field: request.form.get(field, "")
            for field in PREFERENCE_FIELDS_FROM_PROFILE
            if field in request.form
        }
        if preference_updates:
            update_preferences(preference_updates, allow_future_fields=False)
        return redirect(url_for("profile.profile_page", saved="profile"))

    return _render_profile_page()


@bp.post("/preferences")
def preferences():
    theme = request.form.get("theme", "day")
    language = request.form.get("language", "en")

    updates = {
        "theme": "night" if theme == "night" else "day",
        "language": language if language in available_language_codes() else "en",
        "privacy_mode": _checkbox_on("privacy_mode"),
        "show_sensitive_data": _checkbox_on("show_sensitive_data"),
    }
    update_preferences(updates, allow_future_fields=False)
    return redirect(url_for("profile.profile_page", saved="preferences"))


@bp.post("/preferences/quick")
def preferences_quick():
    preferences = load_preferences()
    action = str(request.form.get("action") or "").strip()

    updates = {}

    if action == "toggle_theme":
        current_theme = str(preferences.get("theme") or "day")
        updates["theme"] = "night" if current_theme != "night" else "day"

    elif action == "toggle_language":
        current_language = str(preferences.get("language") or "en")
        updates["language"] = "it" if current_language != "it" else "en"

    elif action == "toggle_privacy":
        next_privacy_mode = not bool(preferences.get("privacy_mode"))
        updates["privacy_mode"] = next_privacy_mode

        # Important:
        # When privacy is turned on from the quick card, actually hide values.
        if next_privacy_mode:
            updates["show_sensitive_data"] = False

    if updates:
        update_preferences(updates, allow_future_fields=False)

    return redirect(url_for("profile.profile_page", saved="preferences"))

@bp.post("/navigation/hide")
def navigation_hide():
    hide_page(request.form.get("page_id", ""))
    return redirect(_profile_navigation_url(saved="navigation"))


@bp.post("/navigation/show")
def navigation_show():
    show_page(request.form.get("page_id", ""))
    return redirect(_profile_navigation_url(saved="navigation"))


@bp.post("/navigation/move")
def navigation_move():
    target_index = request.form.get("target_index")
    parsed_index = None
    if target_index not in {None, ""}:
        try:
            parsed_index = int(str(target_index))
        except ValueError:
            parsed_index = None
    move_page(
        request.form.get("page_id", ""),
        direction=request.form.get("direction", ""),
        target_index=parsed_index,
    )
    return redirect(_profile_navigation_url(saved="navigation"))


@bp.post("/navigation/group")
def navigation_group():
    set_group_collapsed(
        request.form.get("group_id", ""),
        collapsed=_checkbox_on("collapsed"),
    )
    return redirect(_profile_navigation_url(saved="navigation"))


@bp.post("/navigation/restore")
def navigation_restore():
    restore_default_navigation()
    return redirect(_profile_navigation_url(saved="navigation_restored"))


@bp.post("/avatar")
def avatar_upload():
    action = str(request.form.get("action") or "upload").strip().casefold()
    if action == "remove":
        _remove_current_avatar()
        return redirect(url_for("profile.profile_page", saved="avatar_removed"))

    file = request.files.get("avatar")
    if not file or not file.filename:
        return redirect(url_for("profile.profile_page", error="avatar_missing"))

    try:
        _save_avatar(file)
    except ValueError as exc:
        return redirect(url_for("profile.profile_page", error=str(exc)))
    return redirect(url_for("profile.profile_page", saved="avatar"))


@bp.get("/avatar")
def avatar():
    profile = load_profile()
    filename = str(profile.get("profile_image") or "").strip()
    if not filename:
        abort(404)

    safe_filename = _safe_avatar_filename(filename)
    if not safe_filename:
        abort(404)
    path = _avatar_dir() / safe_filename
    if not _is_path_inside(path, _avatar_dir()) or not path.exists() or not path.is_file():
        abort(404)
    if path.suffix.lower() not in ALLOWED_AVATAR_EXTENSIONS:
        abort(404)

    mimetype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return send_file(path, mimetype=mimetype, conditional=True, max_age=3600)


def _render_profile_page():
    user = current_user() or {}
    profile = load_profile()
    preferences = load_preferences()
    display_name = display_name_from_profile(profile, username=str(user.get("username") or ""))
    initials = initials_from_profile(profile, username=str(user.get("username") or ""))
    status = _status_message(request.args.get("saved"), request.args.get("error"))

    return render_template(
        "profile/profile.html",
        profile=profile,
        preferences=preferences,
        display_name=display_name,
        initials=initials,
        user=user,
        status=status,
        account_options=account_options_for_forms(include_credit=False),
        currency_options=currency_options_for_forms(),
        date_format_options=DATE_FORMAT_OPTIONS,
        theme_options=THEME_OPTIONS,
        avatar_max_mb=MAX_AVATAR_BYTES // (1024 * 1024),
        navigation_groups=get_effective_navigation(include_hidden=True),
    )



def _profile_navigation_url(*, saved: str) -> str:
    return f"{url_for('profile.profile_page', saved=saved)}#navigation"

def _avatar_dir() -> Path:
    path = get_user_data_dir() / AVATAR_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def _save_avatar(file: FileStorage) -> None:
    if request.content_length and request.content_length > MAX_AVATAR_BYTES + 256_000:
        raise ValueError("avatar_too_large")

    original_name = secure_filename(file.filename or "")
    suffix = Path(original_name).suffix.lower()
    if suffix not in ALLOWED_AVATAR_EXTENSIONS:
        raise ValueError("avatar_type")

    stable_name = f"avatar{suffix}"
    destination = _avatar_dir() / stable_name
    if not _is_path_inside(destination, _avatar_dir()):
        raise ValueError("avatar_type")

    _remove_avatar_files(except_filename=stable_name)
    file.save(destination)

    if not destination.exists() or destination.stat().st_size <= 0:
        destination.unlink(missing_ok=True)
        raise ValueError("avatar_empty")
    if destination.stat().st_size > MAX_AVATAR_BYTES:
        destination.unlink(missing_ok=True)
        raise ValueError("avatar_too_large")

    profile = load_profile()
    profile["profile_image"] = stable_name
    save_profile(profile)


def _remove_current_avatar() -> None:
    profile = load_profile()
    filename = str(profile.get("profile_image") or "").strip()
    if filename:
        safe_filename = _safe_avatar_filename(filename)
        if safe_filename:
            path = _avatar_dir() / safe_filename
            if _is_path_inside(path, _avatar_dir()):
                path.unlink(missing_ok=True)
    _remove_avatar_files()
    profile["profile_image"] = ""
    save_profile(profile)


def _remove_avatar_files(*, except_filename: str | None = None) -> None:
    keep = str(except_filename or "")
    for path in _avatar_dir().glob("avatar.*"):
        if path.name == keep:
            continue
        if path.is_file() and path.suffix.lower() in ALLOWED_AVATAR_EXTENSIONS:
            path.unlink(missing_ok=True)


def _safe_avatar_filename(filename: str) -> str | None:
    safe = secure_filename(filename)
    if not safe or Path(safe).name != safe or Path(safe).suffix.lower() not in ALLOWED_AVATAR_EXTENSIONS:
        return None
    return safe


def _is_path_inside(path: Path, base: Path) -> bool:
    try:
        resolved = path.resolve()
        root = base.resolve()
    except OSError:
        return False
    return resolved == root or root in resolved.parents


def _checkbox_on(name: str) -> bool:
    return str(request.form.get(name, "")).strip().casefold() in {"1", "true", "yes", "on"}


def _status_message(saved: str | None, error: str | None) -> dict[str, str] | None:
    if error:
        known_errors = {"avatar_missing", "avatar_type", "avatar_empty", "avatar_too_large", "backup_missing", "backup_type", "backup_invalid", "backup_restore_failed"}
        key = f"profile.status.{error}" if error in known_errors else "profile.status.generic_error"
        return {"tone": "error", "key": key}

    known_saved = {"profile", "preferences", "avatar", "avatar_removed", "navigation", "navigation_restored", "backup_imported"}
    if saved in known_saved:
        return {"tone": "success", "key": f"profile.status.{saved}"}
    return None
