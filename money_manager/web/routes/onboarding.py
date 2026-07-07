from __future__ import annotations

from datetime import date
from flask import Blueprint, redirect, render_template, request, url_for

from money_manager.config import MAIN_ACCOUNT_KEY
from money_manager.repositories.debts import append_debt
from money_manager.repositories.recurring import append_recurring
from money_manager.services.account_config_service import update_account_from_form
from money_manager.services.currency_service import currency_options_for_forms
from money_manager.services.i18n_service import available_language_codes
from money_manager.services.onboarding_service import (
    mark_onboarding_completed,
    mark_onboarding_incomplete,
    onboarding_state,
)
from money_manager.services.preferences_service import normalize_theme_value, update_preferences
from money_manager.services.profile_service import update_profile
from money_manager.services.savings_goal_service import create_goal_from_form
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
                "theme": normalize_theme_value(theme),
                "currency": str(currency or "EUR").upper(),
                "onboarding_completed": True,
            },
            allow_future_fields=True,
        )
        _update_main_account_from_onboarding(request.form)
        _create_onboarding_seed_items(request.form)
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


def _create_onboarding_seed_items(form) -> None:
    today = date.today().isoformat()
    account_id = MAIN_ACCOUNT_KEY
    account_label = str(form.get("main_account_name") or "Main").strip() or "Main"

    salary_amount = _money(form.get("salary_amount"))
    if salary_amount > 0:
        append_recurring({
            "name": str(form.get("salary_name") or "Salary").strip() or "Salary",
            "type": "income",
            "amount": salary_amount,
            "frequency": 1,
            "day_of_month": _day(form.get("salary_day"), default=10),
            "category": str(form.get("salary_category") or "Salary").strip() or "Salary",
            "account": account_label,
            "account_id": account_id,
            "account_name_snapshot": account_label,
            "start_date": today,
        })

    for index in range(1, 4):
        name = str(form.get(f"recurring_name_{index}") or "").strip()
        amount = _money(form.get(f"recurring_amount_{index}"))
        if not name or amount <= 0:
            continue
        append_recurring({
            "name": name,
            "type": "expense",
            "amount": amount,
            "frequency": 1,
            "day_of_month": _day(form.get(f"recurring_day_{index}"), default=1),
            "category": str(form.get(f"recurring_category_{index}") or "Bills").strip() or "Bills",
            "account": account_label,
            "account_id": account_id,
            "account_name_snapshot": account_label,
            "start_date": today,
        })

    for index in range(1, 3):
        name = str(form.get(f"debt_name_{index}") or "").strip()
        amount = _money(form.get(f"debt_amount_{index}"))
        if not name or amount <= 0:
            continue
        append_debt({
            "name": name,
            "creditor": str(form.get(f"debt_creditor_{index}") or "").strip(),
            "original_amount": amount,
            "remaining_amount": amount,
            "category": "Debt",
            "account": account_label,
            "account_id": account_id,
            "account_name_snapshot": account_label,
            "start_date": today,
            "due_date": _clean_iso_date(form.get(f"debt_due_date_{index}")),
            "description": "Created from onboarding wizard",
            "status": "active",
        })

    goal_name = str(form.get("goal_title") or "").strip()
    if goal_name and _money(form.get("goal_target_amount")) > 0:
        create_goal_from_form({
            "title": goal_name,
            "target_amount": form.get("goal_target_amount"),
            "current_amount": form.get("goal_current_amount"),
            "monthly_contribution": form.get("goal_monthly_contribution"),
            "due_date": form.get("goal_due_date"),
            "category": form.get("goal_category") or "Savings",
            "account_id": account_id,
            "description": "Created from onboarding wizard",
        })


def _money(value) -> float:
    try:
        return max(0.0, float(str(value or "").replace(",", ".")))
    except (TypeError, ValueError):
        return 0.0


def _day(value, *, default: int) -> int:
    try:
        return max(1, min(31, int(float(value or default))))
    except (TypeError, ValueError):
        return default


def _clean_iso_date(value) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        return date.fromisoformat(raw[:10]).isoformat()
    except ValueError:
        return ""


def _safe_next(value: str | None) -> str:
    text = str(value or "").strip()
    if not text or not text.startswith("/") or text.startswith("//") or "\\" in text:
        return ""
    return text
