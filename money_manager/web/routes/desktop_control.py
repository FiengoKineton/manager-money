from __future__ import annotations

import hmac
import json
import os
import socket
from urllib.parse import urlsplit

from flask import Blueprint, Response, jsonify, render_template, request

bp = Blueprint("desktop_control", __name__, url_prefix="/system")


def _loopback_request() -> bool:
    remote = str(request.remote_addr or "").strip().casefold()
    return remote in {"127.0.0.1", "::1", "localhost"} or remote.startswith("127.")


def _launcher_environment() -> tuple[str, int, str] | None:
    host = str(os.environ.get("MONEY_MANAGER_LAUNCHER_CONTROL_HOST") or "127.0.0.1").strip()
    token = str(os.environ.get("MONEY_MANAGER_LAUNCHER_CONTROL_TOKEN") or "").strip()
    try:
        port = int(os.environ.get("MONEY_MANAGER_LAUNCHER_CONTROL_PORT") or 0)
    except (TypeError, ValueError):
        port = 0
    if not token or port <= 0:
        return None
    return host, port, token


def _safe_return_url(raw: str | None) -> str:
    value = str(raw or "").strip()
    if not value:
        return "/"
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc:
        if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            return "/"
        value = parsed.path or "/"
        if parsed.query:
            value += f"?{parsed.query}"
    if not value.startswith("/") or value.startswith("//"):
        return "/"
    return value


def _send_launcher_command(command: str, **values) -> dict:
    environment = _launcher_environment()
    if environment is None:
        return {"ok": False, "error": "The desktop launcher is not managing this server."}
    host, port, token = environment
    payload = {"command": command, "token": token, **values}
    try:
        with socket.create_connection((host, port), timeout=2.0) as connection:
            connection.settimeout(2.0)
            connection.sendall(json.dumps(payload).encode("utf-8") + b"\n")
            raw = connection.recv(8192).split(b"\n", 1)[0]
        response = json.loads(raw.decode("utf-8")) if raw else {}
        return response if isinstance(response, dict) else {"ok": False, "error": "Invalid launcher response."}
    except Exception as exc:
        return {"ok": False, "error": f"The launcher could not be contacted: {exc}"}


@bp.get("/ready")
def ready() -> Response:
    response = jsonify(
        ready=True,
        app="Money Manager",
        instance_id=str(os.environ.get("MONEY_MANAGER_SERVER_INSTANCE_ID") or "direct-server"),
        launcher_managed=bool(_launcher_environment()),
    )
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return response


@bp.post("/internal-shutdown")
def internal_shutdown() -> Response:
    if not _loopback_request():
        return jsonify(ok=False, error="Loopback requests only."), 403
    expected = str(os.environ.get("MONEY_MANAGER_LAUNCHER_CONTROL_TOKEN") or "")
    supplied = str(request.headers.get("X-MoneyManager-Launcher-Token") or "")
    if not expected or not hmac.compare_digest(expected, supplied):
        return jsonify(ok=False, error="Invalid launcher token."), 403

    controller = request.environ.get("werkzeug.server.shutdown")
    extension = None
    try:
        from flask import current_app

        extension = current_app.extensions.get("money_manager_server_controller")
    except Exception:
        extension = None

    accepted = False
    if extension is not None and hasattr(extension, "request_shutdown"):
        accepted = bool(extension.request_shutdown(delay=0.45))
    elif callable(controller):
        controller()
        accepted = True
    return jsonify(ok=accepted, action=str((request.get_json(silent=True) or {}).get("action") or "shutdown"))


@bp.post("/restart")
def restart_app() -> Response:
    return_url = _safe_return_url(request.form.get("next") or request.referrer)
    old_instance_id = str(os.environ.get("MONEY_MANAGER_SERVER_INSTANCE_ID") or "direct-server")
    result = _send_launcher_command("restart", return_url=return_url, old_instance_id=old_instance_id)
    status = 202 if result.get("ok") else 503
    return (
        render_template(
            "system/restarting.html",
            accepted=bool(result.get("ok")),
            error=str(result.get("error") or ""),
            return_url=return_url,
            old_instance_id=old_instance_id,
        ),
        status,
    )
