from flask import Blueprint, render_template, request

from money_manager.config import TRANSACTION_TYPES, default_date_range
from money_manager.repositories.pending import load_pending
from money_manager.services.account_service import main_account_transactions
from money_manager.services.analytics_service import apply_transaction_filters, build_dashboard_metrics, period_summaries
from money_manager.services.debt_service import generate_debt_payments
from money_manager.services.overview_service import build_overview_context
from money_manager.services.pending_service import pending_total, process_pending
from money_manager.services.recurring_service import generate_recurring
from money_manager.services.transaction_service import load_transactions
from money_manager.web.transaction_filter_state import resolve_transaction_filter_state

bp = Blueprint("dashboard", __name__)


def _refresh_automatic_items() -> None:
    # Generate queues, but do not mark pending items as paid automatically.
    # Payments can now be executed or delayed explicitly from the Pending page.
    generate_recurring()
    generate_debt_payments()
    process_pending(credit_only=True)


@bp.route("/")
def overview():
    _refresh_automatic_items()
    return render_template("core/overview_simple.html", **build_overview_context())


@bp.route("/overview")
@bp.route("/overview/detailed")
def overview_detailed():
    _refresh_automatic_items()
    return render_template("core/overview.html", **build_overview_context())


@bp.route("/dashboard")
def index():
    _refresh_automatic_items()

    df = load_transactions()
    main_df = main_account_transactions(df)
    stats_this_month, stats_3_months = period_summaries(main_df)

    start_default, end_default = default_date_range()
    filter_state = resolve_transaction_filter_state(request.args, start_default, end_default, TRANSACTION_TYPES)
    start = filter_state["start"]
    end = filter_state["end"]
    types = filter_state["types"]
    categories = filter_state["categories"]
    query = filter_state["query"]
    amount_min = filter_state["amount_min"]
    amount_max = filter_state["amount_max"]

    filtered = apply_transaction_filters(df, start, end, types, categories, query, amount_min, amount_max)
    filtered_main = main_account_transactions(filtered)
    metrics = build_dashboard_metrics(filtered_main, start, end)

    all_categories = sorted(main_df["category"].dropna().unique().tolist()) if not main_df.empty else []
    pending_rows = load_pending()
    current_pending_total = pending_total(pending_rows)

    return render_template(
        "core/index.html",
        totals=metrics["totals"],
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
        net_after_pending=metrics["totals"]["net"] - current_pending_total,
        pending_this_month=current_pending_total,
        charts=metrics["charts"],
    )
