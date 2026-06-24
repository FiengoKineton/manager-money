"""Compatibility entry point.

You can run either:
    python app.py
or:
    python run.py
"""
import os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
os.environ.setdefault("MONEY_MANAGER_DATA_HOME", str(PROJECT_DIR / "MoneyManagerData"))

from money_manager.app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
