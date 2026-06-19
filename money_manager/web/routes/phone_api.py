from __future__ import annotations

from flask import Blueprint, jsonify

from money_manager.services.phone_experience_service import build_phone_experience_summary

bp = Blueprint("phone_api", __name__, url_prefix="/phone/api")


@bp.get("/summary")
def phone_summary():
    """Read-only phone experience data. It does not affect the desktop web app."""
    return jsonify(build_phone_experience_summary())
