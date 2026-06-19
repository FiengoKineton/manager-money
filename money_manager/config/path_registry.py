"""Human-readable registry of the app's important runtime files and calculation entry points.

This file is intentionally descriptive.  The normal app logic still lives in the
repositories and services; this registry gives future changes one clear place to
see which files feed the expensive calculations and which functions are worth
warming/caching.
"""

from __future__ import annotations

from pathlib import Path

from money_manager.config.paths import (
    CURRENCIES_JSON,
    DATA_DIR,
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

# JSON files that are declared in other config modules to avoid circular imports.
CUSTOM_ACCOUNTS_JSON = DATA_DIR / "accounts.json"

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

# Files that affect precomputed app calculations.  The cache service fingerprints
# exactly these paths before it reuses a cached result.
CACHE_INPUT_FILES: tuple[Path, ...] = tuple(DATA_FILE_REGISTRY.values())

# Entry points that are expensive enough to be warmed when the app starts or soon
# after CSV/JSON data changes.  Values are import strings on purpose: this file
# stays lightweight and does not import services while Flask is starting.
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

# Useful write entry points.  These are the places that usually make cached
# calculations stale.  Low-level CSV writes notify the cache service automatically,
# so this list is mainly documentation for future debugging/refactoring.
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
    """Return path metadata for optional debugging/admin screens."""
    rows: list[dict[str, str]] = []
    for key, path in DATA_FILE_REGISTRY.items():
        rows.append({
            "key": key,
            "path": str(path),
            "exists": "yes" if path.exists() else "no",
        })
    return rows


# Feature-level architecture registry.  Imported lazily by tools/admin pages, not
# by the normal calculation flow.
FEATURE_REGISTRY = "money_manager.config.feature_registry.FEATURES"
FEATURE_GROUP_REGISTRY = "money_manager.config.feature_registry.FEATURE_GROUPS"
