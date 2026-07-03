import os
from datetime import timedelta
from pathlib import Path
from flask import Flask, make_response, request

from money_manager.config import ensure_runtime_directories
from money_manager.web.context import register_context_processors
from money_manager.web.routes import register_routes


def _is_prefetch_request() -> bool:
    """Detect browser document prefetches and skip expensive route work.

    A local app should not decrypt data, run dashboard builders, or start
    maintenance threads for speculative navigation requests.  Real clicks do not
    send these headers and continue through the normal route logic.
    """
    try:
        if request.method != "GET":
            return False
        purpose = " ".join([
            request.headers.get("Purpose", ""),
            request.headers.get("Sec-Purpose", ""),
            request.headers.get("X-Purpose", ""),
        ]).casefold()
        if "prefetch" not in purpose and "prerender" not in purpose:
            return False
        endpoint = str(request.endpoint or "")
        if endpoint.startswith("static"):
            return False
        accept = str(request.headers.get("Accept", ""))
        return not accept or "text/html" in accept or "*/*" in accept
    except Exception:
        return False


def create_app() -> Flask:
    package_dir = Path(__file__).resolve().parent
    project_root = package_dir.parent

    ensure_runtime_directories()
    try:
        from money_manager.cache.startup_cache import clear_cache_on_startup

        clear_cache_on_startup()
    except Exception:
        pass
    try:
        from money_manager.security.decrypted_export_service import cleanup_expired_decrypted_exports_throttled

        cleanup_expired_decrypted_exports_throttled(force=True)
    except Exception:
        pass

    app = Flask(
        __name__,
        template_folder=str(package_dir / "web" / "templates"),
        static_folder=str(project_root / "static"),
        static_url_path="/static",
    )

    app.config.update(
        SECRET_KEY=os.environ.get("MONEY_MANAGER_SECRET_KEY", "dev-local-change-me"),
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )

    @app.before_request
    def _money_manager_skip_prefetch_requests():
        # Register this before blueprints so auth/onboarding guards do not
        # decrypt or repair user files for browser speculation requests.
        if _is_prefetch_request():
            response = make_response("", 204)
            response.headers["X-MoneyManager-Prefetch-Skipped"] = "1"
            response.headers["Cache-Control"] = "no-store"
            return response

    register_context_processors(app)
    register_routes(app)

    from money_manager.cache.request_cache import clear_request_cache, init_request_cache

    @app.before_request
    def _money_manager_init_request_cache():
        init_request_cache()
        try:
            from money_manager.performance.request_profiler import start as _perf_start

            _perf_start()
        except Exception:
            pass

    @app.teardown_request
    def _money_manager_clear_request_cache(error=None):
        clear_request_cache(error)

    @app.after_request
    def _money_manager_cleanup_exports(response):
        try:
            from money_manager.security.decrypted_export_service import cleanup_expired_decrypted_exports_throttled

            cleanup_expired_decrypted_exports_throttled()
        except Exception:
            pass
        try:
            from money_manager.performance.request_profiler import finish as _perf_finish

            response = _perf_finish(response)
        except Exception:
            pass
        return response

    return app
