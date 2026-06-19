from money_manager.services.account_service import main_account_transactions
from money_manager.services.transaction_service import load_transactions
from money_manager.services.notification_service import build_notification_context_cached
from money_manager.utils.formatting import format_euro, format_number, thousands_format_filter
from money_manager.utils.stats import summary_totals


def _topbar_main_bank_net() -> float:
    try:
        df = load_transactions()
        main_df = main_account_transactions(df)
        return float(summary_totals(main_df)["net"])
    except Exception:
        return 0.0


def register_context_processors(app):
    app.add_template_filter(format_number, "money")
    app.add_template_filter(format_euro, "euro")
    app.add_template_filter(thousands_format_filter, "format")

    @app.context_processor
    def inject_endpoint_checker():
        def endpoint_exists(endpoint):
            return endpoint in app.view_functions

        return {
            "endpoint_exists": endpoint_exists,
            "topbar_main_bank_net": _topbar_main_bank_net(),
            "topbar_notifications": build_notification_context_cached(),
        }
