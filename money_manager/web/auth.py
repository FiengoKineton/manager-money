from __future__ import annotations

import hmac
import os

from flask import Blueprint, current_app, redirect, render_template, request, session, url_for

bp = Blueprint("auth", __name__)


def _configured_password() -> str:
    return current_app.config.get("MONEY_MANAGER_PASSWORD", "") or os.environ.get("MONEY_MANAGER_PASSWORD", "")


def _is_logged_in() -> bool:
    return session.get("money_manager_logged_in") is True


@bp.before_app_request
def require_login():
    if request.endpoint in {"auth.login"}:
        return None

    if _is_logged_in():
        return None

    next_url = request.full_path if request.query_string else request.path
    return redirect(url_for("auth.login", next=next_url))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if _is_logged_in():
        return redirect(request.args.get("next") or url_for("dashboard.overview"))

    error = None

    if request.method == "POST":
        password = request.form.get("password", "")
        expected = _configured_password()

        if not expected:
            error = "App password is not configured. Set MONEY_MANAGER_PASSWORD before starting the app."
        elif hmac.compare_digest(password, expected):
            session.clear()
            session.permanent = True
            session["money_manager_logged_in"] = True
            return redirect(request.args.get("next") or url_for("dashboard.overview"))
        else:
            error = "Wrong password."

    return render_template("login.html", error=error)


@bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))