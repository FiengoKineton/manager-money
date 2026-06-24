"""Start Money Manager for access from a phone on the same Wi-Fi network.

Run from the repository root:
    python run_phone_server.py

Then open the printed http://<your-pc-ip>:5000 address on the phone.
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


def _prepare() -> None:
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    os.chdir(PROJECT_ROOT)
    os.environ.setdefault("MONEY_MANAGER_DATA_HOME", str(PROJECT_ROOT / "MoneyManagerData"))
    os.environ.setdefault("MONEY_MANAGER_PHONE_MODE", "1")


def _local_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"
    finally:
        sock.close()


def _parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start Money Manager for phone access on local Wi-Fi.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to bind. Default: 5000")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind. Keep 0.0.0.0 for phone access.")
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = _parse_args(argv)
    _prepare()
    from money_manager.app import create_app

    app = create_app()
    ip = _local_ip()
    print("")
    print("Money Manager phone server is running.")
    print(f"Open this on your phone while connected to the same Wi-Fi: http://{ip}:{args.port}")
    print(f"PC/local address: http://127.0.0.1:{args.port}")
    print("Keep this window open. Press Ctrl+C to stop.")
    print("")

    try:
        from waitress import serve as waitress_serve
    except ImportError:
        waitress_serve = None

    if waitress_serve is not None:
        waitress_serve(app, host=args.host, port=args.port, threads=8)
    else:
        app.run(host=args.host, port=args.port, debug=False, use_reloader=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
