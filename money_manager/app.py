import os
from datetime import timedelta
from pathlib import Path
from flask import Flask

from money_manager.config import ensure_runtime_directories
from money_manager.web.context import register_context_processors
from money_manager.web.routes import register_routes


def create_app() -> Flask:
    package_dir = Path(__file__).resolve().parent
    project_root = package_dir.parent

    ensure_runtime_directories()
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
