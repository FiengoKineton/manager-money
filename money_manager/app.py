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

    # Best-effort refresh so the Investments and Currency pages have current
    # web data after each app start. If the network is unavailable, cached/local
    # data is used later and the app still starts normally.
    try:
        from money_manager.services.investment_service import refresh_market_data

        refresh_market_data(force=True)
    except Exception:
        pass

    try:
        from money_manager.services.currency_service import refresh_currency_rates

        refresh_currency_rates(force=True)
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
        MONEY_MANAGER_PASSWORD=os.environ.get("MONEY_MANAGER_PASSWORD", "6730"),
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )

    register_context_processors(app)
    register_routes(app)
    return app
