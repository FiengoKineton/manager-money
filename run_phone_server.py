"""Start Money Manager for access from a phone on the same Wi-Fi network.

Run from the repository root:
    python run_phone_server.py

Then open one of the printed http://<your-pc-ip>:<port> addresses on the phone.
"""
from __future__ import annotations

import argparse
import os
import socket
import sys
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_PORT = 5000
PORT_SCAN_LIMIT = 20


def _prepare() -> None:
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    os.chdir(PROJECT_ROOT)
    os.environ.setdefault("MONEY_MANAGER_DATA_HOME", str(PROJECT_ROOT / "MoneyManagerData"))
    os.environ.setdefault("MONEY_MANAGER_PHONE_MODE", "1")


def _candidate_local_ips() -> list[str]:
    """Return useful LAN addresses without requiring working internet access."""
    ips: list[str] = []

    def add(value: str | None) -> None:
        value = (value or "").strip()
        if not value or value.startswith("127.") or value == "0.0.0.0":
            return
        if value not in ips:
            ips.append(value)

    # Usually gives the active Wi-Fi/LAN IP. It does not actually send packets.
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("8.8.8.8", 80))
            add(sock.getsockname()[0])
        finally:
            sock.close()
    except OSError:
        pass

    # Fallback for offline networks and Windows hostname resolution.
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET, socket.SOCK_STREAM):
            add(info[4][0])
    except OSError:
        pass

    return ips or ["127.0.0.1"]


def _can_bind(host: str, port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, port))
        return True
    except OSError:
        return False


def _choose_port(host: str, requested_port: int, *, strict: bool) -> int:
    if strict or requested_port == 0:
        return requested_port
    for port in range(requested_port, requested_port + PORT_SCAN_LIMIT + 1):
        if _can_bind(host, port):
            return port
    return requested_port


def _parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start Money Manager for phone access on local Wi-Fi.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to bind. Default: 5000")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind. Keep 0.0.0.0 for phone access.")
    parser.add_argument(
        "--strict-port",
        action="store_true",
        help="Fail instead of automatically moving to the next free port when the requested port is busy.",
    )
    return parser.parse_args(argv)


def _print_access_instructions(host: str, port: int) -> None:
    print("")
    print("Money Manager phone server is running.")
    print("Open one of these addresses on your phone while it is connected to the same Wi-Fi as this PC:")
    for ip in _candidate_local_ips():
        print(f"  http://{ip}:{port}")
    print(f"PC/local address: http://127.0.0.1:{port}")
    if host in {"127.0.0.1", "localhost"}:
        print("Warning: this server is bound to localhost only, so phones cannot reach it. Use --host 0.0.0.0.")
    print("Keep this window open. If the phone cannot connect, allow Python/Money Manager through Windows Firewall for private networks.")
    print("Press Ctrl+C to stop.")
    print("")


def main(argv: Iterable[str] | None = None) -> int:
    args = _parse_args(argv)
    _prepare()

    selected_port = _choose_port(args.host, args.port, strict=args.strict_port)
    if selected_port != args.port:
        print(f"Port {args.port} is already busy; using port {selected_port} instead.")

    try:
        from money_manager.app import create_app
    except ModuleNotFoundError as exc:
        missing = exc.name or str(exc)
        print(f"Missing Python dependency: {missing}")
        print("Run: .venv\\Scripts\\python.exe -m pip install -r requirements.txt")
        return 1

    app = create_app()
    _print_access_instructions(args.host, selected_port)

    try:
        from waitress import serve as waitress_serve
    except ImportError:
        waitress_serve = None

    try:
        if waitress_serve is not None:
            waitress_serve(app, host=args.host, port=selected_port, threads=8)
        else:
            app.run(host=args.host, port=selected_port, debug=False, use_reloader=False)
    except OSError as exc:
        print("")
        print(f"Could not start the phone server on {args.host}:{selected_port}: {exc}")
        print("Try closing the other Money Manager window, or run: python run_phone_server.py --port 5001")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
