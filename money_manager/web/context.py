from copy import deepcopy

from flask import request

from money_manager.config.user_defaults import DEFAULT_PREFERENCES, DEFAULT_PROFILE
from money_manager.services.account_service import main_account_transactions
from money_manager.services.i18n_service import available_languages, current_language, t
from money_manager.services.notification_service import build_notification_context_cached
from money_manager.services.navigation_service import get_effective_navigation
from money_manager.services.preferences_service import load_preferences
from money_manager.services.profile_service import display_name_from_profile, initials_from_profile, load_profile
from money_manager.services.transaction_service import load_transactions
from money_manager.utils.formatting import format_euro, format_number, thousands_format_filter
from money_manager.utils.privacy import format_masked_amount, mask_amount, mask_iban, mask_money, mask_text, should_mask_sensitive
from money_manager.utils.stats import summary_totals
from money_manager.web.auth import current_user as auth_current_user, is_authenticated


def _topbar_main_bank_net() -> float:
    if not is_authenticated():
        return 0.0
    try:
        df = load_transactions()
        main_df = main_account_transactions(df)
        return float(summary_totals(main_df)["net"])
    except Exception:
        return 0.0


def _topbar_notifications() -> dict:
    if not is_authenticated():
        return {"count": 0, "unread_count": 0, "has_unread_candidate": False, "items": []}
    try:
        return build_notification_context_cached()
    except Exception:
        return {"count": 0, "unread_count": 0, "has_unread_candidate": False, "items": []}


def _current_user_config_context(user: dict | None) -> dict:
    profile = deepcopy(DEFAULT_PROFILE)
    preferences = deepcopy(DEFAULT_PREFERENCES)
    username = str(user.get("username") or "") if user else ""

    if user and is_authenticated():
        try:
            profile = load_profile()
        except Exception:
            profile.update(
                {
                    "first_name": str(user.get("first_name") or ""),
                    "last_name": str(user.get("last_name") or ""),
                    "display_name": str(user.get("display_name") or ""),
                }
            )
        try:
            preferences = load_preferences()
        except Exception:
            preferences = deepcopy(DEFAULT_PREFERENCES)

    privacy_mode = bool(preferences.get("privacy_mode", False))
    mask_sensitive_data = should_mask_sensitive(preferences)
    language = current_language()
    return {
        "current_user_profile": profile,
        "current_user_preferences": preferences,
        "user_display_name": display_name_from_profile(profile, username=username),
        "user_initials": initials_from_profile(profile, username=username),
        "privacy_mode": privacy_mode,
        "mask_sensitive_data": mask_sensitive_data,
        "privacy_reveal_enabled": privacy_mode and not mask_sensitive_data,
        "selected_language": language,
        "current_language": language,
        "available_languages": available_languages(),
        "selected_theme": str(preferences.get("theme") or "day"),
    }


def register_context_processors(app):
    app.add_template_filter(format_number, "money")
    app.add_template_filter(format_euro, "euro")
    app.add_template_filter(thousands_format_filter, "format")
    app.add_template_filter(mask_iban, "mask_iban")
    app.add_template_filter(mask_amount, "mask_amount")
    app.add_template_filter(format_masked_amount, "format_masked_amount")
    app.add_template_filter(mask_money, "money_masked")
    app.add_template_filter(mask_text, "text_masked")

    @app.context_processor
    def inject_endpoint_checker():
        def endpoint_exists(endpoint):
            return endpoint in app.view_functions

        user = auth_current_user()
        try:
            sidebar_navigation = (
                get_effective_navigation(current_endpoint=request.endpoint)
                if user and is_authenticated()
                else []
            )
        except Exception:
            sidebar_navigation = []

        context = {
            "endpoint_exists": endpoint_exists,
            "sidebar_navigation": sidebar_navigation,
            "topbar_main_bank_net": _topbar_main_bank_net(),
            "topbar_notifications": _topbar_notifications(),
            "current_user": user,
            "current_user_id": user.get("id") if user else None,
            "is_authenticated": is_authenticated(),
            "t": t,
        }
        context.update(_current_user_config_context(user))
        return context
