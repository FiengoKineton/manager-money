from flask import Blueprint, abort, redirect, render_template, request, send_file, url_for

from money_manager.config import TRANSACTION_TYPES, default_date_range
from money_manager.repositories.pending import load_pending
from money_manager.services.analytics_service import apply_transaction_filters, build_dashboard_metrics, period_summaries
from money_manager.services.debt_service import generate_debt_payments
from money_manager.services.dashboard_calculation_service import get_dashboard_overview_cached
from money_manager.services.pending_service import process_pending, sync_credit_account_statements
from money_manager.services.recurring_service import generate_recurring
from money_manager.services.transaction_service import load_transactions
from money_manager.utils.stats import summary_totals
from money_manager.web.context import resolve_request_scope, scope_template_context
from money_manager.web.transaction_filter_state import resolve_transaction_filter_state

bp = Blueprint("dashboard", __name__)


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


def _refresh_automatic_items() -> None:
    # Generate queues, but do not mark pending items as paid automatically.
    # Payments can now be executed or delayed explicitly from the Pending page.
    generate_recurring()
    generate_debt_payments()
    sync_credit_account_statements()
    process_pending(credit_only=True)


@bp.route("/")
def home():
    return redirect(url_for("accounts.accounts_page"))


@bp.route("/home")
def overview():
    _refresh_automatic_items()
    selected_scope = resolve_request_scope(request)
    context = get_dashboard_overview_cached(scope=selected_scope["scope"])
    context.update(scope_template_context(selected_scope))
    return render_template("core/overview_simple.html", **context)

@bp.route("/overview")
@bp.route("/overview/detailed")
def overview_detailed():
    _refresh_automatic_items()
    selected_scope = resolve_request_scope(request)
    context = get_dashboard_overview_cached(scope=selected_scope["scope"])
    context.update(scope_template_context(selected_scope))
    return render_template("core/overview.html", **context)

@bp.route("/dashboard")
def index():
    _refresh_automatic_items()

    selected_scope = resolve_request_scope(request)
    from money_manager.services.account_scope_service import pending_total_for_scope, scope_balance_summary, transactions_for_scope

    df = load_transactions()
    scoped_df = transactions_for_scope(df, selected_scope)
    stats_this_month, stats_3_months = period_summaries(scoped_df)

    start_default, end_default = default_date_range()
    filter_state = resolve_transaction_filter_state(request.args, start_default, end_default, TRANSACTION_TYPES)
    start = filter_state["start"]
    end = filter_state["end"]
    types = filter_state["types"]
    categories = filter_state["categories"]
    query = filter_state["query"]
    amount_min = filter_state["amount_min"]
    amount_max = filter_state["amount_max"]
    has_effective_filters = bool(filter_state.get("has_effective_filters"))
    has_non_date_filters = bool(filter_state.get("has_non_date_filters"))

    # Display rows/charts use the active visual filters. By default that means
    # Jan-1st→today, because the dashboard should stay readable.
    filtered = apply_transaction_filters(scoped_df, start, end, types, categories, query, amount_min, amount_max)
    filtered_main = filtered

    # Money-position cards must not accidentally ignore old/opening rows just
    # because the default display window starts on Jan 1st. Only switch the
    # calculation source when the user actually narrows filters/date range.
    calculation_main = filtered_main if has_effective_filters else scoped_df
    display_totals = summary_totals(filtered_main)
    metrics = build_dashboard_metrics(
        filtered_main,
        start,
        end,
        totals_df=calculation_main,
        opening_source_df=scoped_df,
        include_opening_balance=not has_non_date_filters,
    )

    all_categories = sorted(scoped_df["category"].dropna().unique().tolist()) if not scoped_df.empty else []
    current_pending_total = pending_total_for_scope(selected_scope)
    scope_summary = scope_balance_summary(selected_scope)
    scoped_net = float(scope_summary.get("net_balance", metrics["totals"].get("net", 0.0)) or 0.0)
    scoped_net_after_pending = float(scope_summary.get("net_after_pending", scoped_net - current_pending_total) or 0.0)

    # The dashboard charts and income/expense cards can follow the visible date
    # window, but the hero balance must be the actual selected Conto/global net.
    # Otherwise an account with an initial balance of €100 and €23.95 expenses
    # incorrectly shows -€23.95 instead of €76.05/its real scoped balance.
    metrics["totals"]["net"] = scoped_net
    metrics["totals"]["total_availability"] = scoped_net
    money_calculation_label = "selected filters" if has_effective_filters else ("selected Conto balance" if selected_scope.get("is_account") else "All Conti balance")

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
        net_after_pending=scoped_net_after_pending,
        scope_balance=scope_summary,
        pending_this_month=current_pending_total,
        charts=metrics["charts"],
        has_effective_filters=has_effective_filters,
        has_non_date_filters=has_non_date_filters,
        uses_full_history_for_calculations=not has_effective_filters,
        money_calculation_label=money_calculation_label,
        visual_scope_label=filter_state.get("display_scope_label", "current year"),
        cumulative_balance_uses_opening=not has_non_date_filters,
        **scope_template_context(selected_scope),
    )
