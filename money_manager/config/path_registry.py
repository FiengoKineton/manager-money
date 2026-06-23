"""Compatibility wrapper around the central storage data registry."""

from __future__ import annotations

from pathlib import Path

from money_manager.config.user_paths import get_current_user_id, user_data_path
from money_manager.storage.data_file_service import data_registry_diagnostics
from money_manager.storage.data_registry import all_definitions


def _runtime_user_path(relative_path: str):
    return user_data_path(relative_path)


DATA_FILE_REGISTRY: dict[str, Path] = {
    definition.name: _runtime_user_path(definition.relative_path)
    for definition in all_definitions("user")
    if definition.file_type in {"json", "csv"} and definition.relative_path
}

CACHE_INPUT_FILES: tuple[Path, ...] = tuple(
    path for name, path in DATA_FILE_REGISTRY.items() if "cache" not in name
)

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
    user_id = get_current_user_id()
    rows: list[dict[str, str]] = []
    for item in data_registry_diagnostics(user_id=user_id):
        rows.append({
            "key": item["name"],
            "path": item["expected_path"],
            "exists": "yes" if item["exists"] else "no",
            "scope": item["scope"],
            "file_type": item["file_type"],
            "backup_policy": item["backup_policy"],
            "encryption_policy": item["future_encryption_policy"],
            "sensitive_level": item["sensitive_level"],
        })
    return rows


FEATURE_REGISTRY = "money_manager.config.feature_registry.FEATURES"
FEATURE_GROUP_REGISTRY = "money_manager.config.feature_registry.FEATURE_GROUPS"
