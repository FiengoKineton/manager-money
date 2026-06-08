"""Compatibility entry point.

You can run either:
    python app.py
or:
    python run.py
"""
from money_manager.app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
