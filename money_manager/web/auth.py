from __future__ import annotations

from functools import wraps

from flask import Blueprint, redirect, render_template, request, session, url_for

from money_manager.users.user_manager import (
    authenticate_user,
    create_user,
    ensure_user_data_folder,
    get_user_by_id,
    has_any_user,
)

bp = Blueprint("auth", __name__)

PUBLIC_ENDPOINTS = {"auth.login", "auth.register", "static"}
ONBOARDING_ALLOWED_ENDPOINTS = {"onboarding.onboarding_page", "onboarding.reset_onboarding", "auth.logout"}


def is_authenticated() -> bool:
    user_id = session.get("user_id")
    if not user_id:
        return False
    return get_user_by_id(str(user_id)) is not None


def current_user() -> dict | None:
    user_id = session.get("user_id")
    return get_user_by_id(str(user_id)) if user_id else None


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
        ensure_user_data_folder(str(session.get("user_id")), create_files=True)
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
        return redirect(request.args.get("next") or url_for("dashboard.overview"))

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
                _login_user(user)
                return redirect(request.args.get("next") or url_for("dashboard.overview"))

    return render_template("auth/register.html", error=error, first_user=first_user)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if not has_any_user():
        return redirect(url_for("auth.register", next=request.args.get("next") or url_for("dashboard.overview")))

    if is_authenticated():
        return redirect(request.args.get("next") or url_for("dashboard.overview"))

    error = None

    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        user = authenticate_user(username, password)
        if user:
            _login_user(user)
            return redirect(request.args.get("next") or url_for("dashboard.overview"))
        error = "Wrong username or password."

    return render_template("auth/login.html", error=error)


@bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


def _login_user(user: dict) -> None:
    session.clear()
    session.permanent = True
    session["user_id"] = str(user.get("id"))
    session["username"] = str(user.get("username"))
    session["display_name"] = str(user.get("display_name") or user.get("username"))
