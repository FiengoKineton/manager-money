from __future__ import annotations

from flask import Blueprint, redirect, url_for

bp = Blueprint("phone", __name__)


@bp.get("/phone")
@bp.get("/phone/")
def phone_home():
    """Friendly phone entry point.

    The phone UI is the same Flask app with phone-only CSS/JS activated by the
    device breakpoint. This route avoids a confusing 404 when someone opens
    /phone from the URL printed by the phone launcher.
    """
    return redirect(url_for("dashboard.index", ui="phone"))
