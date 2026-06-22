"""Local desktop startup entry point for Money Manager.

Run from the repository root with:
    python run_money_manager.py

It is also safe to call this file from another working directory because the
script resolves paths relative to its own location.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5000


def _prepare_import_path() -> None:
    """Make repo-local imports and relative runtime paths reliable."""
    project_root_str = str(PROJECT_ROOT)
    if project_root_str not in sys.path:
        sys.path.insert(0, project_root_str)
    os.chdir(PROJECT_ROOT)


def create_flask_app():
    """Import and create the Flask application from the package factory."""
    _prepare_import_path()
    from money_manager.app import create_app

    return create_app()


def _browser_url(host: str, port: int) -> str:
    # Browsers should use localhost even when the server binds all interfaces.
    browser_host = "127.0.0.1" if host in {"0.0.0.0", "::", ""} else host
    return f"http://{browser_host}:{port}"


def _open_browser_later(url: str, delay_seconds: float = 1.2) -> None:
    def _open() -> None:
        try:
            webbrowser.open(url)
        except Exception:
            # Browser auto-open is a convenience. The server should still run.
            pass

    timer = threading.Timer(delay_seconds, _open)
    timer.daemon = True
    timer.start()


def _parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start the local Money Manager webapp.")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Host to bind. Default: 127.0.0.1")
    parser.add_argument("--port", default=DEFAULT_PORT, type=int, help="Port to bind. Default: 5000")
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open the browser automatically.",
    )
    parser.add_argument(
        "--flask-dev-server",
        action="store_true",
        help="Use Flask's built-in server instead of Waitress when Waitress is installed.",
    )
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = _parse_args(argv)
    app = create_flask_app()
    url = _browser_url(args.host, args.port)

    if not args.no_browser:
        _open_browser_later(url)

    print(f"Money Manager is starting on {url}")
    print("Press Ctrl+C in this window to stop it.")

    if not args.flask_dev_server:
        try:
            from waitress import serve as waitress_serve
        except ImportError:
            waitress_serve = None

        if waitress_serve is not None:
            # Waitress can print harmless queue-depth warnings when the browser
            # loads many assets at once. Keep the local launcher output clean.
            logging.getLogger("waitress.queue").setLevel(logging.ERROR)
            waitress_serve(app, host=args.host, port=args.port, threads=8)
            return 0

    app.run(host=args.host, port=args.port, debug=False, use_reloader=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
