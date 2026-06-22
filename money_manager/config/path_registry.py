"""Human-readable registry of runtime user data files and calculation entry points."""

from __future__ import annotations

from pathlib import Path

from money_manager.config.paths import (
    CURRENCIES_JSON,
    DEBTS_CSV,
    DEBT_RULES_CSV,
    EXPENSE_PROJECTS_CSV,
    EXPENSE_PROJECT_MOVEMENTS_CSV,
    EXPENSE_PROJECT_PLANNED_ITEMS_CSV,
    INTERNAL_TRANSFERS_CSV,
    INVESTMENT_ASSETS_CSV,
    INVESTMENT_MARKET_CACHE_JSON,
    PARENT_SUPPORT_CSV,
    PARENT_SUPPORT_RULES_CSV,
    PAYABLES_CSV,
    PENDING_CSV,
    RECEIVABLES_CSV,
    RECURRING_CSV,
    SPARAGNAT_CSV,
    TRANSACTION_FILES,
)
from money_manager.config.user_paths import user_data_path

CUSTOM_ACCOUNTS_JSON = user_data_path("accounts.json")

DATA_FILE_REGISTRY: dict[str, Path] = {
    "accounts": CUSTOM_ACCOUNTS_JSON,
    "currencies": CURRENCIES_JSON,
    "expenses": TRANSACTION_FILES["expense"],
    "incomes": TRANSACTION_FILES["income"],
    "investments": TRANSACTION_FILES["investment"],
    "pending": PENDING_CSV,
    "internal_transfers": INTERNAL_TRANSFERS_CSV,
    "recurring_rules": RECURRING_CSV,
    "sparagnat": SPARAGNAT_CSV,
    "parent_support": PARENT_SUPPORT_CSV,
    "parent_support_rules": PARENT_SUPPORT_RULES_CSV,
    "debts": DEBTS_CSV,
    "debt_rules": DEBT_RULES_CSV,
    "receivables": RECEIVABLES_CSV,
    "payables": PAYABLES_CSV,
    "expense_projects": EXPENSE_PROJECTS_CSV,
    "expense_project_movements": EXPENSE_PROJECT_MOVEMENTS_CSV,
    "expense_project_planned_items": EXPENSE_PROJECT_PLANNED_ITEMS_CSV,
    "investment_assets": INVESTMENT_ASSETS_CSV,
    "investment_market_cache": INVESTMENT_MARKET_CACHE_JSON,
}

CACHE_INPUT_FILES: tuple[Path, ...] = tuple(DATA_FILE_REGISTRY.values())

CALCULATION_ENTRYPOINTS: dict[str, str] = {
    "transactions.load_all": "money_manager.services.transaction_service.load_transactions",
    "overview.context": "money_manager.services.overview_service.build_overview_context",
    "analysis.metrics": "money_manager.services.analytics_service.build_analysis_metrics_cached",
    "forecast.defaults": "money_manager.services.forecast_service.build_forecast_defaults",
    "quick_log.context": "money_manager.services.quick_log_service.quick_log_context",
    "notifications.context": "money_manager.services.notification_service.build_notification_context_cached",
    "phone.experience.summary": "money_manager.services.phone_experience_service.build_phone_experience_summary_cached",
    "investment.overview_snapshot": "money_manager.services.investment_service.overview_snapshot",
    "investment.habit_snapshot": "money_manager.services.investment_service.investment_habit_snapshot",
}

WRITE_ENTRYPOINTS: dict[str, str] = {
    "transactions.append": "money_manager.repositories.transactions.append_transaction",
    "transactions.update": "money_manager.repositories.transactions.update_transaction",
    "transactions.delete": "money_manager.repositories.transactions.delete_transaction",
    "pending.append": "money_manager.repositories.pending.append_pending",
    "pending.update": "money_manager.repositories.pending.update_pending",
    "recurring.append": "money_manager.repositories.recurring.append_recurring",
    "debts.append": "money_manager.repositories.debts.append_debt",
    "payables.append": "money_manager.repositories.payables.append_payable",
    "receivables.append": "money_manager.repositories.receivables.append_receivable",
    "projects.append": "money_manager.repositories.expense_projects.append_project",
    "accounts.custom_save": "money_manager.config.accounts.save_custom_account",
}


def describe_runtime_paths() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for key, path in DATA_FILE_REGISTRY.items():
        try:
            exists = "yes" if path.exists() else "no"
            resolved = str(path)
        except Exception:
            exists = "no-active-user"
            resolved = repr(path)
        rows.append({"key": key, "path": resolved, "exists": exists})
    return rows


FEATURE_REGISTRY = "money_manager.config.feature_registry.FEATURES"
FEATURE_GROUP_REGISTRY = "money_manager.config.feature_registry.FEATURE_GROUPS"
