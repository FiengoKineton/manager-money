from pathlib import Path

from flask import Flask

from money_manager.config import ensure_runtime_directories
from money_manager.web.context import register_context_processors
from money_manager.web.routes import register_routes


def create_app() -> Flask:
    package_dir = Path(__file__).resolve().parent
    project_root = package_dir.parent

    ensure_runtime_directories()

    app = Flask(
        __name__,
        template_folder=str(package_dir / "web" / "templates"),
        static_folder=str(project_root / "static"),
        static_url_path="/static",
    )

    register_context_processors(app)
    register_routes(app)
    return app
