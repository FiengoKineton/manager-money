from __future__ import annotations

import os
import time
from typing import Any

try:
    from flask import g, has_request_context, request
except Exception:  # pragma: no cover
    g = None  # type: ignore

    def has_request_context() -> bool:
        return False

SLOW_MS = float(os.environ.get("MONEY_MANAGER_SLOW_REQUEST_MS", "750") or 750)
ADD_HEADER = os.environ.get("MONEY_MANAGER_PERF_HEADER", "1").strip() != "0"
LOG_SLOW = os.environ.get("MONEY_MANAGER_LOG_SLOW_REQUESTS", "1").strip() != "0"


def start() -> None:
    if has_request_context():
        setattr(g, "_money_manager_request_started_at", time.perf_counter())


def finish(response: Any):
    if not has_request_context():
        return response
    started = getattr(g, "_money_manager_request_started_at", None)
    if not started:
        return response
    elapsed_ms = (time.perf_counter() - float(started)) * 1000.0
    if ADD_HEADER:
        try:
            response.headers["X-MoneyManager-Request-MS"] = f"{elapsed_ms:.1f}"
        except Exception:
            pass
    if LOG_SLOW and elapsed_ms >= SLOW_MS:
        try:
            from flask import current_app

            current_app.logger.warning(
                "Slow request %.1f ms %s %s",
                elapsed_ms,
                getattr(request, "method", ""),
                getattr(request, "full_path", getattr(request, "path", "")),
            )
        except Exception:
            pass
    return response
