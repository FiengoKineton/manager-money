from __future__ import annotations

from functools import wraps
import os
import threading

from flask import Blueprint, g, redirect, render_template, request, session, url_for

from money_manager.security.key_manager import is_encryption_enabled
from money_manager.security.session_vault import is_unlocked, lock_vault, unlock_user
from money_manager.cache.precompute_service import warm_cache_on_login
from money_manager.users.user_manager import (
    authenticate_user,
    create_user,
    ensure_user_data_folder,
    get_user_by_id,
    has_any_user,
)

bp = Blueprint("auth", __name__)

_USER_FILES_READY: set[tuple[str, int]] = set()
_USER_SCHEMA_REPAIR_RUNNING: set[tuple[str, int]] = set()
_USER_SCHEMA_LOCK = threading.RLock()


def _data_schema_version() -> int:
    try:
        from money_manager.config.app_home import load_app_version

        return int(load_app_version().get("data_schema_current") or 0)
    except Exception:
        return 0


def _ensure_user_files_once(user_id: str) -> None:
    """Keep request-time file checks cheap.

    Encrypted storage made the old full schema repair expensive because it
    decrypted many files before every first page after login/unlock.  The request
    path now only ensures folders exist.  A full repair is queued in the
    background once per process/schema version, while individual readers still
    lazily create/repair the exact file they need.
    """
    key = (str(user_id), _data_schema_version())
    ensure_user_data_folder(user_id, create_files=False)
    with _USER_SCHEMA_LOCK:
        if key in _USER_FILES_READY:
            return
        _USER_FILES_READY.add(key)
    if os.environ.get("MONEY_MANAGER_AUTO_SCHEMA_REPAIR", "0").strip() == "1":
        _schedule_schema_repair(user_id, key)


def _schedule_schema_repair(user_id: str, key: tuple[str, int]) -> None:
    with _USER_SCHEMA_LOCK:
        if key in _USER_SCHEMA_REPAIR_RUNNING:
            return
        _USER_SCHEMA_REPAIR_RUNNING.add(key)

    def _run() -> None:
        try:
            from money_manager.config.user_paths import using_user

            with using_user(str(user_id)):
                ensure_user_data_folder(user_id, create_files=True)
        except Exception:
            with _USER_SCHEMA_LOCK:
                _USER_FILES_READY.discard(key)
        finally:
            with _USER_SCHEMA_LOCK:
                _USER_SCHEMA_REPAIR_RUNNING.discard(key)

    thread = threading.Thread(target=_run, name=f"money-manager-schema-repair-{user_id}", daemon=True)
    thread.start()


PUBLIC_ENDPOINTS = {"auth.login", "auth.register", "static"}
UNLOCK_ALLOWED_ENDPOINTS = {"security.unlock", "security.lock", "auth.logout", "static"}
ONBOARDING_ALLOWED_ENDPOINTS = {"onboarding.onboarding_page", "onboarding.reset_onboarding", "auth.logout", "security.unlock", "security.lock"}


def is_authenticated() -> bool:
    return current_user() is not None


def current_user() -> dict | None:
    user_id = session.get("user_id")
    if not user_id:
        return None
    cache_key = "_money_manager_current_user"
    cached = getattr(g, cache_key, None)
    if isinstance(cached, dict) and str(cached.get("id") or "") == str(user_id):
        return cached
    user = get_user_by_id(str(user_id))
    setattr(g, cache_key, user)
    return user


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not is_authenticated():
            next_url = request.full_path if request.query_string else request.path
            return redirect(url_for("auth.login", next=next_url))
        return view(*args, **kwargs)

    return wrapped


@bp.before_app_request
def require_login():
    endpoint = request.endpoint or ""
    if endpoint in PUBLIC_ENDPOINTS or endpoint.startswith("static"):
        return None

    if not has_any_user():
        return redirect(url_for("auth.register", next=request.path))

    if is_authenticated():
        user_id = str(session.get("user_id") or "")

        encryption_enabled = is_encryption_enabled(user_id)
        vault_locked = encryption_enabled and not is_unlocked(user_id)
        unlock_allowed = endpoint in UNLOCK_ALLOWED_ENDPOINTS or endpoint.startswith("static")

        # Important:
        # The unlock/logout/lock pages must be reachable while the vault is locked.
        # Do NOT create/repair encrypted user files here because that requires the DEK.
        if vault_locked:
            if unlock_allowed:
                ensure_user_data_folder(user_id, create_files=False)
                return None

            next_url = request.full_path if request.query_string else request.path
            return redirect(url_for("security.unlock", next=next_url))

        # Vault is unlocked, or encryption is disabled.
        # Now it is safe to create/repair encrypted user files, but only a full
        # repair pass once per user/schema version.
        _ensure_user_files_once(user_id)

        if _should_redirect_to_onboarding(endpoint):
            next_url = request.full_path if request.query_string else request.path
            return redirect(url_for("onboarding.onboarding_page", next=next_url))

        return None

    next_url = request.full_path if request.query_string else request.path
    return redirect(url_for("auth.login", next=next_url))


def _should_redirect_to_onboarding(endpoint: str) -> bool:
    if endpoint in ONBOARDING_ALLOWED_ENDPOINTS or endpoint.startswith("static"):
        return False
    try:
        from money_manager.services.onboarding_service import should_start_onboarding

        return should_start_onboarding(str(session.get("user_id") or ""))
    except Exception:
        return False


@bp.route("/register", methods=["GET", "POST"])
def register():
    if is_authenticated():
        return redirect(request.args.get("next") or url_for("accounts.accounts_page"))

    error = None
    first_user = not has_any_user()

    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        first_name = request.form.get("first_name", "")
        last_name = request.form.get("last_name", "")

        if not username.strip():
            error = "Username is required."
        elif not password:
            error = "Password is required."
        elif password != confirm_password:
            error = "The two passwords do not match."
        else:
            try:
                user = create_user(username, password, first_name=first_name, last_name=last_name)
            except ValueError as exc:
                error = str(exc)
            else:
                _login_user(user, password=password)
                return redirect(request.args.get("next") or url_for("accounts.accounts_page"))

    return render_template("auth/register.html", error=error, first_user=first_user)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if not has_any_user():
        return redirect(url_for("auth.register", next=request.args.get("next") or url_for("accounts.accounts_page")))

    if is_authenticated():
        return redirect(request.args.get("next") or url_for("accounts.accounts_page"))

    error = None

    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        user = authenticate_user(username, password)
        if user:
            try:
                _login_user(user, password=password)
            except Exception:
                error = "Password verified, but the encrypted vault could not be unlocked."
            else:
                return redirect(request.args.get("next") or url_for("accounts.accounts_page"))
        elif error is None:
            error = "Wrong username or password."

    return render_template("auth/login.html", error=error)


@bp.post("/logout")
def logout():
    lock_vault()
    session.clear()
    return redirect(url_for("auth.login"))


def _login_user(user: dict, *, password: str | None = None) -> None:
    session.clear()
    session.permanent = True
    user_id = str(user.get("id"))
    session["user_id"] = user_id
    session["username"] = str(user.get("username"))
    session["display_name"] = str(user.get("display_name") or user.get("username"))

    # Old installs may have users created before encryption became mandatory.
    # When the password is available, upgrade the active user folder immediately
    # so subsequent add/edit/delete requests keep writing encrypted files.
    if password:
        if not is_encryption_enabled(user_id):
            from money_manager.security.encryption_migration_service import migrate_user_to_encrypted_storage

            migrate_user_to_encrypted_storage(user_id, password)
        unlock_user(user_id, password)
    try:
        warm_cache_on_login(user_id)
    except Exception:
        pass
