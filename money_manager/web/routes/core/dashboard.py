from flask import Blueprint, abort, jsonify, redirect, render_template, request, send_file, url_for
from time import monotonic
import threading


from money_manager.config import TRANSACTION_TYPES
from money_manager.services.analytics_service import apply_transaction_filters, build_dashboard_metrics, period_summaries
from money_manager.services.calculation_service import cached_context
from money_manager.services.debt_service import generate_debt_payments
from money_manager.services.dashboard_calculation_service import get_dashboard_overview_cached
from money_manager.services.pending_service import process_pending, sync_credit_account_statements
from money_manager.services.recurring_service import generate_recurring, recurring_forecast_for_current_month
from money_manager.services.transaction_service import load_transactions
from money_manager.utils.stats import summary_totals
from money_manager.web.context import resolve_request_scope, scope_template_context
from money_manager.web.dashboard_period import dashboard_period_state, dashboard_query_filter_state
from money_manager.web.auth import current_user
from money_manager.config.user_paths import using_user
from money_manager.utils.formatting import format_euro

bp = Blueprint("dashboard", __name__)

_AUTO_REFRESH_INTERVAL_SECONDS = 60
_auto_refresh_lock = threading.RLock()
_auto_refresh_running: set[str] = set()
_last_auto_refresh_at_by_user: dict[str, float] = {}


def _current_user_id() -> str:
    user = current_user() or {}
    return str(user.get("id") or "").strip()


@bp.route("/user-plots/<path:filename>")
def user_plot(filename):
    from money_manager.config.user_paths import user_plot_path

    try:
        path = user_plot_path(filename)
    except ValueError:
        abort(404)
    if not path.exists() or not path.is_file():
        abort(404)
    if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".svg"}:
        abort(404)
    return send_file(path, conditional=True, max_age=300)


def _refresh_automatic_items_sync(user_id: str) -> None:
    with using_user(user_id):
        # Generate queues and execute only safe automatic items: credit settlements
        # plus recurring rules explicitly marked Pay without asking.
        generate_recurring()
        generate_debt_payments()
        sync_credit_account_statements()
        process_pending(credit_only=True)


def _schedule_automatic_items_refresh(*, force: bool = False) -> None:
    """Run heavy recurring/pending/credit maintenance outside the page request.

    Page navigation must be read-mostly and fast.  The old implementation did
    this maintenance synchronously before rendering /home, /overview and
    /dashboard, which could make a simple click wait on encrypted file IO.
    """
    user_id = _current_user_id()
    if not user_id:
        return

    now = monotonic()
    with _auto_refresh_lock:
        last_run = _last_auto_refresh_at_by_user.get(user_id, 0.0)
        if not force and now - last_run < _AUTO_REFRESH_INTERVAL_SECONDS:
            return
        if user_id in _auto_refresh_running:
            return
        _auto_refresh_running.add(user_id)

    def _run() -> None:
        try:
            _refresh_automatic_items_sync(user_id)
            with _auto_refresh_lock:
                _last_auto_refresh_at_by_user[user_id] = monotonic()
        finally:
            with _auto_refresh_lock:
                _auto_refresh_running.discard(user_id)

    thread = threading.Thread(target=_run, name=f"money-manager-auto-refresh-{user_id}", daemon=True)
    thread.start()


@bp.route("/")
def home():
    return redirect(url_for("dashboard.index"))




@bp.get("/api/topbar-summary")
def topbar_summary_api():
    selected_scope = resolve_request_scope(request)
    try:
        # The dashboard may explicitly ask for a one-month net. This query-only
        # override is never persisted, so every other page immediately returns
        # to the normal full-history topbar balance.
        if str(request.args.get("period_mode") or "").casefold() == "month":
            from money_manager.services.account_scope_service import transactions_for_scope

            scoped = transactions_for_scope(load_transactions(), selected_scope)
            period = dashboard_period_state(request.args, scoped)
            rows = apply_transaction_filters(
                scoped, period["start"], period["end"], TRANSACTION_TYPES, [], "", "", ""
            )
            net = float(summary_totals(rows).get("net", 0.0) or 0.0)
            label = f"{period['label']} net"
        elif selected_scope.get("is_account") and selected_scope.get("account_id"):
            from money_manager.services.account_scope_service import scope_balance_summary

            summary = scope_balance_summary(selected_scope)
            net = float(summary.get("net_balance", 0.0) or 0.0)
            label = f"{selected_scope.get('label') or selected_scope.get('account_id')} net"
        else:
            from money_manager.services.dashboard_calculation_service import get_quick_overview_cached

            net = float(get_quick_overview_cached().get("net_worth", 0.0) or 0.0)
            label = "All Conti net"
    except Exception:
        net = 0.0
        label = "All Conti net"
    return jsonify({"ok": True, "net": net, "net_formatted": format_euro(net), "label": label})

@bp.route("/home")
def overview():
    _schedule_automatic_items_refresh()
    selected_scope = resolve_request_scope(request)
    context = get_dashboard_overview_cached(scope=selected_scope["scope"])
    context.update(scope_template_context(selected_scope))
    return render_template("core/overview_simple.html", **context)

@bp.route("/overview")
@bp.route("/overview/detailed")
def overview_detailed():
    _schedule_automatic_items_refresh()
    selected_scope = resolve_request_scope(request)
    context = get_dashboard_overview_cached(scope=selected_scope["scope"])
    context.update(scope_template_context(selected_scope))
    return render_template("core/overview.html", **context)

@bp.route("/dashboard", methods=["GET", "POST"])
def index():
    _schedule_automatic_items_refresh()

    if request.method == "POST":
        action = str(request.form.get("action") or "")
        if action in {"add_dashboard_category", "add_custom_category"}:
            from money_manager.services.category_icon_service import set_category_icon
            from money_manager.services.custom_category_service import add_custom_category

            transaction_type = str(request.form.get("transaction_type") or "expense").strip().casefold()
            category_name = " ".join(str(request.form.get("category_name") or "").split())
            category_icon = str(request.form.get("category_icon") or "").strip()
            account_id = str(request.form.get("account_id") or "").strip()
            try:
                add_custom_category(transaction_type, category_name)
                if category_icon:
                    set_category_icon(category_name, category_icon, transaction_type)
                params = {"category_added": category_name}
                if account_id:
                    params["account_id"] = account_id
                for name in ("period_mode", "period_month", "period_year"):
                    value = str(request.form.get(name) or "").strip()
                    if value:
                        params[name] = value
                return redirect(url_for("dashboard.index", **params))
            except ValueError as exc:
                params = {"category_error": str(exc)}
                if account_id:
                    params["account_id"] = account_id
                for name in ("period_mode", "period_month", "period_year"):
                    value = str(request.form.get(name) or "").strip()
                    if value:
                        params[name] = value
                return redirect(url_for("dashboard.index", **params))

    selected_scope = resolve_request_scope(request)
    from money_manager.services.account_scope_service import pending_total_for_scope, scope_balance_summary, transactions_for_scope
    from money_manager.services.custom_category_service import effective_categories_by_type

    df = load_transactions()
    scoped_df = transactions_for_scope(df, selected_scope)
    stats_this_month, stats_3_months = period_summaries(scoped_df)

    filter_state = dashboard_query_filter_state(request.args, scoped_df, TRANSACTION_TYPES)
    period_state = filter_state["period"]
    start = filter_state["start"]
    end = filter_state["end"]
    types = filter_state["types"]
    categories = filter_state["categories"]
    query = filter_state["query"]
    amount_min = filter_state["amount_min"]
    amount_max = filter_state["amount_max"]
    has_non_date_filters = bool(filter_state["has_non_date_filters"])
    has_effective_filters = bool(filter_state["has_effective_filters"])

    # Period-only rows determine the dashboard hero net. Advanced category/type
    # filters affect cards/charts but do not silently redefine the account net.
    period_df = apply_transaction_filters(
        scoped_df,
        start,
        end,
        TRANSACTION_TYPES,
        [],
        "",
        "",
        "",
    )
    filtered = apply_transaction_filters(
        scoped_df,
        start,
        end,
        types,
        categories,
        query,
        amount_min,
        amount_max,
    )

    display_totals = summary_totals(filtered)
    metrics = cached_context(
        "dashboard_overview",
        lambda: build_dashboard_metrics(
            filtered,
            start,
            end,
            totals_df=filtered,
            opening_source_df=None,
            include_opening_balance=False,
            opening_balance_override=None,
        ),
        params={
            "view": "dashboard_metrics_v2",
            "scope": selected_scope["scope"],
            "period_mode": period_state["mode"],
            "start": start,
            "end": end,
            "types": tuple(types),
            "categories": tuple(categories),
            "query": query,
            "amount_min": amount_min,
            "amount_max": amount_max,
        },
    )

    configured_categories = effective_categories_by_type()
    observed_categories = (
        scoped_df["category"].dropna().astype(str).tolist()
        if not scoped_df.empty and "category" in scoped_df.columns
        else []
    )
    all_categories = sorted({
        value
        for value in [
            *observed_categories,
            *configured_categories.get("expense", []),
            *configured_categories.get("income", []),
            *configured_categories.get("investment", []),
        ]
        if str(value).strip()
    }, key=lambda value: (str(value).casefold(), str(value)))

    current_pending_total = pending_total_for_scope(selected_scope)
    scope_summary = scope_balance_summary(selected_scope, df=df)
    full_history_net = float(scope_summary.get("net_balance", metrics["totals"].get("net", 0.0)) or 0.0)

    if period_state["mode"] == "month":
        dashboard_net = float(summary_totals(period_df).get("net", 0.0) or 0.0)
        dashboard_net_after_pending = dashboard_net
        money_calculation_label = f"{period_state['label']} only · dashboard"
    else:
        dashboard_net = full_history_net
        dashboard_net_after_pending = float(scope_summary.get("net_after_pending", full_history_net - current_pending_total) or 0.0)
        money_calculation_label = "full history · first log to latest log"

    current_month_recurring = recurring_forecast_for_current_month()

    try:
        from money_manager.services.notification_service import build_notification_context_cached

        dashboard_notifications = build_notification_context_cached()
        dashboard_new_notifications = [
            item for item in dashboard_notifications.get("items", [])
            if item.get("is_unread", True)
        ]
    except Exception:
        dashboard_notifications = {"items": [], "count": 0, "unread_count": 0}
        dashboard_new_notifications = []

    try:
        from money_manager.services.payable_service import immediate_payable_reminders

        dashboard_payable_reminders = immediate_payable_reminders(
            limit=6,
            scope=selected_scope,
        )
    except Exception:
        dashboard_payable_reminders = []

    recurring_expenses_this_month = [
        item for item in current_month_recurring.get("items", [])
        if item.get("type") == "expense"
    ][:8]
    recurring_incomes_this_month = [
        item for item in current_month_recurring.get("items", [])
        if item.get("type") == "income"
    ][:6]

    try:
        from money_manager.services.account_calculation_service import get_account_dashboard_summary_cached

        account_snapshot = get_account_dashboard_summary_cached()
        dashboard_current_accounts = list(account_snapshot.get("current_accounts_overview") or account_snapshot.get("accounts") or [])
    except Exception:
        dashboard_current_accounts = []
    if selected_scope.get("is_account") and selected_scope.get("account_id"):
        selected_key = str(selected_scope.get("account_id") or "")
        dashboard_current_accounts = [
            row for row in dashboard_current_accounts
            if str(row.get("key") or row.get("id") or "") == selected_key
        ]
    dashboard_current_accounts = dashboard_current_accounts[:4]

    metrics["totals"]["net"] = dashboard_net
    metrics["totals"]["total_availability"] = dashboard_net

    return render_template(
        "core/index.html",
        totals=metrics["totals"],
        display_totals=display_totals,
        start=start,
        end=end,
        active_types=types,
        all_types=TRANSACTION_TYPES,
        categories_selected=categories,
        categories_all=all_categories,
        q=query,
        amount_min=amount_min,
        amount_max=amount_max,
        stats_this_month=stats_this_month,
        stats_3_months=stats_3_months,
        net_after_pending=dashboard_net_after_pending,
        full_history_net=full_history_net,
        scope_balance=scope_summary,
        pending_this_month=current_pending_total,
        current_month_recurring=current_month_recurring,
        recurring_expenses_this_month=recurring_expenses_this_month,
        recurring_incomes_this_month=recurring_incomes_this_month,
        dashboard_notifications=dashboard_notifications,
        dashboard_new_notifications=dashboard_new_notifications,
        dashboard_payable_reminders=dashboard_payable_reminders,
        dashboard_current_accounts=dashboard_current_accounts,
        charts=metrics["charts"],
        has_effective_filters=has_effective_filters,
        has_non_date_filters=has_non_date_filters,
        uses_full_history_for_calculations=period_state["mode"] == "all",
        uses_transaction_initial_conditions=False,
        money_calculation_label=money_calculation_label,
        visual_scope_label=period_state["label"],
        cumulative_balance_uses_opening=False,
        dashboard_period=period_state,
        category_added=str(request.args.get("category_added") or ""),
        category_error=str(request.args.get("category_error") or ""),
        transaction_window={
            "start": start,
            "end": end,
            "opening_net": 0.0,
            "historical_rows": 0,
        },
        **scope_template_context(selected_scope),
    )

