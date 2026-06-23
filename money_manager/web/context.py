from copy import deepcopy
from urllib.parse import urlencode

from flask import request, url_for

from money_manager.config.user_defaults import DEFAULT_PREFERENCES, DEFAULT_PROFILE
from money_manager.services.i18n_service import available_languages, current_language, t
from money_manager.services.notification_service import build_notification_context_cached
from money_manager.services.navigation_service import get_effective_navigation
from money_manager.services.preferences_service import load_preferences
from money_manager.services.profile_service import display_name_from_profile, initials_from_profile, load_profile
from money_manager.services.transaction_service import load_transactions
from money_manager.utils.formatting import format_euro, format_number, thousands_format_filter
from money_manager.utils.privacy import format_masked_amount, mask_amount, mask_iban, mask_money, mask_text, should_mask_sensitive
from money_manager.web.auth import current_user as auth_current_user, is_authenticated


def _topbar_main_bank_net() -> float:
    if not is_authenticated():
        return 0.0
    try:
        from money_manager.services.account_scope_service import global_balance_summary

        return float(global_balance_summary().get("net_balance", 0.0) or 0.0)
    except Exception:
        return 0.0


def _topbar_scope_net_context(active_account: dict | None = None) -> dict:
    """Net pill shown in the top bar.

    Global pages show All Conti net. When the URL is locked to a selected
    Conto/account, the pill switches to that account's own net.  This avoids the
    old confusing behavior where every page kept showing the global value even
    inside a specific bank account.
    """
    global_net = _topbar_main_bank_net()
    if not is_authenticated():
        return {
            "topbar_global_net": global_net,
            "topbar_display_net": global_net,
            "topbar_net_label": "All Conti net",
            "topbar_net_href": "#",
        }

    active = active_account or active_sidebar_account_context()
    account_id = str(active.get("account_id") or "").strip() if active else ""
    if account_id:
        try:
            from money_manager.services.account_scope_service import scope_balance_summary

            summary = scope_balance_summary(f"account:{account_id}")
            label = str(summary.get("label") or active.get("account_label") or account_id)
            return {
                "topbar_global_net": global_net,
                "topbar_display_net": float(summary.get("net_balance", 0.0) or 0.0),
                "topbar_net_label": f"{label} net",
                "topbar_net_href": url_for("accounts.account_detail", account_key=account_id),
            }
        except Exception:
            pass

    return {
        "topbar_global_net": global_net,
        "topbar_display_net": global_net,
        "topbar_net_label": "All Conti net",
        "topbar_net_href": url_for("accounts.accounts_page") if is_authenticated() else "#",
    }


def resolve_request_scope(flask_request=None, default: str = "global") -> dict:
    """Resolve ?account_id=<id>, ?scope=account:<id>, or global scope."""
    req = flask_request or request
    raw_scope = str(req.args.get("scope") or "").strip()
    account_id = str(req.args.get("account_id") or "").strip()
    try:
        from money_manager.services.account_scope_service import resolve_account_scope

        if account_id and not raw_scope:
            return resolve_account_scope(account_id=account_id)
        return resolve_account_scope(raw_scope or default, account_id=account_id or None)
    except Exception:
        return {
            "kind": "global",
            "scope": "global",
            "account_id": "",
            "label": "Global overview",
            "financial_center_ids": [],
            "included_account_ids": [],
            "dependent_account_ids": [],
            "is_global": True,
            "is_account": False,
        }


def scope_url_args(scope) -> dict:
    selected = scope if isinstance(scope, dict) else None
    if selected is None:
        try:
            from money_manager.services.account_scope_service import resolve_account_scope

            selected = resolve_account_scope(str(scope or "global"))
        except Exception:
            selected = {"scope": str(scope or "global"), "account_id": "", "is_global": str(scope or "global") == "global"}
    if selected.get("is_account") and selected.get("account_id"):
        return {"account_id": selected.get("account_id")}
    return {}


def _scope_switch_links(options: list[dict], selected_scope: dict) -> list[dict]:
    base_args = request.args.to_dict(flat=True)
    base_args.pop("scope", None)
    base_args.pop("account_id", None)

    def _build(account_id: str | None = None) -> str:
        args = dict(base_args)
        if account_id:
            args["account_id"] = account_id
        query = urlencode(args)
        return f"{request.path}?{query}" if query else request.path

    links = [{
        "label": "All accounts",
        "url": _build(None),
        "active": bool(selected_scope.get("is_global")),
        "account_id": "",
        "scope": "global",
    }]
    for option in options:
        account_id = str(option.get("account_id") or "")
        if not account_id:
            continue
        links.append({
            "label": option.get("label") or account_id,
            "url": _build(account_id),
            "active": selected_scope.get("account_id") == account_id,
            "account_id": account_id,
            "scope": option.get("scope") or f"account:{account_id}",
        })
    return links


def scope_template_context(selected_scope: dict | str | None = None) -> dict:
    if not isinstance(selected_scope, dict):
        selected_scope = resolve_request_scope(request, default=str(selected_scope or "global"))
    try:
        from money_manager.services.account_scope_service import financial_centers, scope_options

        options = scope_options()
        centers = financial_centers()
    except Exception:
        options = [{"value": "global", "label": "Global overview", "scope": "global"}]
        centers = []
    query_args = scope_url_args(selected_scope)
    return {
        "selected_scope": selected_scope,
        "selected_scope_key": selected_scope.get("scope", "global"),
        "selected_account_id": selected_scope.get("account_id", ""),
        "scope_label": selected_scope.get("label", "Global overview"),
        "scope_is_global": bool(selected_scope.get("is_global")),
        "scope_is_account": bool(selected_scope.get("is_account")),
        "financial_centers": centers,
        "scope_options": options,
        "scope_links": _scope_switch_links(options, selected_scope),
        "scope_query_args": query_args,
    }


def active_sidebar_account_context() -> dict:
    """Return the account currently locked in the sidebar, if any.

    The app has global modules, but opening a Conto should make the left rail
    act like a local dashboard for that account.  We keep this tiny and
    failure-safe because the context processor runs for every page.
    """
    account_id = str(request.args.get("account_id") or "").strip()
    if not account_id and request.endpoint in {"accounts.account_detail", "accounts.account_payment_method_detail"} and request.view_args:
        account_id = str(request.view_args.get("account_key") or "").strip()
    if not account_id:
        return {"has_active_account": False, "account_id": "", "account_label": ""}
    try:
        from money_manager.services.account_config_service import account_by_key

        account = account_by_key(account_id, include_archived=True) or {}
        label = str(account.get("label") or account.get("name") or account_id)
    except Exception:
        label = account_id
    return {"has_active_account": True, "account_id": account_id, "account_label": label}


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

        active_account_context = active_sidebar_account_context() if user and is_authenticated() else {"has_active_account": False, "account_id": "", "account_label": ""}
        topbar_context = _topbar_scope_net_context(active_account_context)

        context = {
            "endpoint_exists": endpoint_exists,
            "sidebar_navigation": sidebar_navigation,
            "topbar_main_bank_net": topbar_context.get("topbar_global_net", 0.0),
            "topbar_notifications": _topbar_notifications(),
            "current_user": user,
            "current_user_id": user.get("id") if user else None,
            "is_authenticated": is_authenticated(),
            "t": t,
        }
        context.update(topbar_context)
        context.update(_current_user_config_context(user))
        context.update(active_account_context)
        return context
