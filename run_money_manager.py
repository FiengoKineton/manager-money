"""Run the Money Manager Flask application.

The desktop launcher calls this entry point with ``--no-browser`` and supervises
it. Direct terminal startup remains available for development and diagnostics.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path
from typing import Callable, Iterable

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5000


def _prepare_import_path() -> None:
    project_dir = Path(__file__).resolve().parent
    os.chdir(project_dir)
    if str(project_dir) not in sys.path:
        sys.path.insert(0, str(project_dir))
    os.environ.setdefault("MONEY_MANAGER_DATA_HOME", str(project_dir / "MoneyManagerData"))


def create_flask_app():
    _prepare_import_path()
    from money_manager.app import create_app

    return create_app()


def _browser_url(host: str, port: int) -> str:
    browser_host = "127.0.0.1" if host in {"0.0.0.0", "::", ""} else host
    return f"http://{browser_host}:{port}"


def _open_browser_when_ready(url: str, delay_timeout: float = 45.0) -> None:
    def _open() -> None:
        deadline = time.monotonic() + delay_timeout
        ready_url = f"{url}/system/ready"
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(ready_url, timeout=0.8) as response:
                    if 200 <= int(response.status) < 300:
                        webbrowser.open(url)
                        return
            except Exception:
                time.sleep(0.3)
        try:
            webbrowser.open(url)
        except Exception:
            pass

    threading.Thread(target=_open, name="money-manager-browser-opener", daemon=True).start()


class ServerController:
    """Expose a delayed, failure-safe shutdown callback to local control routes."""

    def __init__(self) -> None:
        self._shutdown: Callable[[], None] | None = None
        self._lock = threading.Lock()
        self._requested = False

    def bind(self, callback: Callable[[], None]) -> None:
        self._shutdown = callback

    def request_shutdown(self, *, delay: float = 0.45) -> bool:
        with self._lock:
            if self._requested:
                return True
            callback = self._shutdown
            if callback is None:
                return False
            self._requested = True

        def _close() -> None:
            time.sleep(max(0.05, float(delay)))
            try:
                callback()
            except Exception:
                # The supervising launcher has a terminate/kill fallback.
                pass

        threading.Thread(target=_close, name="money-manager-server-shutdown", daemon=True).start()
        return True


def _parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Money Manager's local web server.")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Host to bind. Default: 127.0.0.1")
    parser.add_argument("--port", default=DEFAULT_PORT, type=int, help="Port to bind. Default: 5000")
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser automatically.")
    parser.add_argument(
        "--flask-dev-server",
        action="store_true",
        help="Use Werkzeug's development server instead of Waitress.",
    )
    return parser.parse_args(argv)


def _run_waitress(app, host: str, port: int, controller: ServerController) -> int:
    from waitress import create_server

    logging.getLogger("waitress.queue").setLevel(logging.ERROR)
    server = create_server(app, host=host, port=port, threads=8)
    controller.bind(server.close)
    server.run()
    return 0


def _run_werkzeug(app, host: str, port: int, controller: ServerController) -> int:
    from werkzeug.serving import make_server

    server = make_server(host, port, app, threaded=True)
    controller.bind(server.shutdown)
    server.serve_forever()
    return 0


def main(argv: Iterable[str] | None = None) -> int:
    args = _parse_args(argv)
    app = create_flask_app()
    controller = ServerController()
    app.extensions["money_manager_server_controller"] = controller
    url = _browser_url(args.host, args.port)

    if not args.no_browser:
        _open_browser_when_ready(url)

    print(f"Money Manager is starting on {url}")
    print("Press Ctrl+C in this window to stop it.")

    if not args.flask_dev_server:
        try:
            return _run_waitress(app, args.host, args.port, controller)
        except ImportError:
            pass

    return _run_werkzeug(app, args.host, args.port, controller)


if __name__ == "__main__":
    raise SystemExit(main())
