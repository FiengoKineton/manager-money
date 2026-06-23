from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, url_for

from money_manager.config import MAIN_ACCOUNT_KEY
from money_manager.services.account_config_service import update_account_from_form
from money_manager.services.currency_service import currency_options_for_forms
from money_manager.services.i18n_service import available_language_codes
from money_manager.services.onboarding_service import (
    mark_onboarding_completed,
    mark_onboarding_incomplete,
    onboarding_state,
)
from money_manager.services.preferences_service import update_preferences
from money_manager.services.profile_service import update_profile
from money_manager.web.routes.profile import DATE_FORMAT_OPTIONS, THEME_OPTIONS

bp = Blueprint("onboarding", __name__, url_prefix="/onboarding")


@bp.route("", methods=["GET", "POST"])
def onboarding_page():
    next_url = _safe_next(request.args.get("next") or request.form.get("next"))
    if request.method == "POST":
        action = str(request.form.get("action") or "complete").strip().casefold()
        if action == "skip":
            mark_onboarding_completed()
            return redirect(next_url or url_for("accounts.accounts_page"))

        language = request.form.get("language", "en")
        theme = request.form.get("theme", "day")
        currency = request.form.get("currency", "EUR")
        update_profile(
            {
                "first_name": request.form.get("first_name", ""),
                "last_name": request.form.get("last_name", ""),
                "bank_name": request.form.get("main_bank_name", ""),
                "default_main_account": MAIN_ACCOUNT_KEY,
            }
        )
        update_preferences(
            {
                "language": language if language in available_language_codes() else "en",
                "theme": "night" if theme == "night" else "day",
                "currency": str(currency or "EUR").upper(),
                "onboarding_completed": True,
            },
            allow_future_fields=True,
        )
        _update_main_account_from_onboarding(request.form)
        mark_onboarding_completed()
        return redirect(next_url or url_for("accounts.accounts_page"))

    state = onboarding_state()
    return render_template(
        "onboarding.html",
        profile=state["profile"],
        preferences=state["preferences"],
        next_url=next_url,
        currency_options=currency_options_for_forms(),
        theme_options=THEME_OPTIONS,
        date_format_options=DATE_FORMAT_OPTIONS,
    )


@bp.post("/reset")
def reset_onboarding():
    mark_onboarding_incomplete()
    return redirect(url_for("onboarding.onboarding_page"))


def _update_main_account_from_onboarding(form) -> None:
    payload = {"currency": str(form.get("currency") or "EUR").upper()}
    main_name = str(form.get("main_account_name") or "").strip()
    main_bank_name = str(form.get("main_bank_name") or "").strip()
    if main_name:
        payload["label"] = main_name
        payload["name"] = main_name
    if main_bank_name:
        payload["institution"] = main_bank_name
    initial_balance = str(form.get("initial_balance") or "").strip()
    if initial_balance:
        payload["initial_balance"] = initial_balance
    update_account_from_form(MAIN_ACCOUNT_KEY, payload)


def _safe_next(value: str | None) -> str:
    text = str(value or "").strip()
    if not text or not text.startswith("/") or text.startswith("//") or "\\" in text:
        return ""
    return text
