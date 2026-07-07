from __future__ import annotations

from money_manager.config.install_paths import BACKUPS_DIR, DATA_HOME, GLOBAL_CACHE_DIR, UPDATE_INBOX_DIR, UPDATES_DIR
from money_manager.config.user_paths import (
    DATA_DIR,
    PROJECT_ROOT,
    SYSTEM_DIR,
    USERS_DIR,
    get_current_user_id,
    get_user_data_dir,
    user_cache_dir,
    user_data_path,
    user_documents_dir,
    user_plots_dir,
)

# Global/system folders.  Money data lives under data/users/{user_id}/ at runtime.
DOCUMENT_FOLDERS = [
    "Cedolini",
    "Tasse - Detrazioni Fiscali",
]

ALLOWED_DOCUMENT_EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".bmp",
    ".svg",
    ".txt",
}

# Runtime-resolved user paths.  These objects behave like pathlib.Path objects,
# but resolve against the authenticated user's data folder only when used.
DOCUMENTS_DIR = user_documents_dir()
PLOTS_DIR = user_plots_dir()
CACHE_DIR = user_cache_dir()
NOTIFICATIONS_STATE_JSON = user_data_path("notification_state.json")
SAVINGS_GOALS_JSON = user_data_path("savings_goals.json")
PLANNED_EXPENSES_JSON = user_data_path("planned_expenses.json")
TIMELINE_EVENTS_JSON = user_data_path("timeline_events.json")
ACCOUNT_RECONCILIATION_JSON = user_data_path("account_reconciliation.json")
SMART_RULES_JSON = user_data_path("smart_rules.json")

TRANSACTION_FILES = {
    "expense": user_data_path("expenses.csv"),
    "income": user_data_path("incomes.csv"),
    "investment": user_data_path("investments.csv"),
}

PENDING_CSV = user_data_path("pending.csv")
INTERNAL_TRANSFERS_CSV = user_data_path("internal_transfers.csv")
CREDIT_SETTLEMENTS_CSV = user_data_path("credit_settlements.csv")
ACCOUNT_EVENTS_JSON = user_data_path("account_events.json")
RECURRING_CSV = user_data_path("recurring.csv")
SPARAGNAT_CSV = user_data_path("sparagnat_fottut.csv")
PARENT_SUPPORT_CSV = user_data_path("parent_support.csv")
PARENT_SUPPORT_RULES_CSV = user_data_path("parent_support_rules.csv")
DEBTS_CSV = user_data_path("debts.csv")
DEBT_RULES_CSV = user_data_path("debt_rules.csv")
RECEIVABLES_CSV = user_data_path("receivables.csv")
PAYABLES_CSV = user_data_path("payables.csv")
EXPENSE_PROJECTS_CSV = user_data_path("expense_projects.csv")
EXPENSE_PROJECT_MOVEMENTS_CSV = user_data_path("expense_project_movements.csv")
EXPENSE_PROJECT_PLANNED_ITEMS_CSV = user_data_path("expense_project_planned_items.csv")
INVESTMENT_ASSETS_CSV = user_data_path("investment_assets.csv")
INVESTMENT_MARKET_CACHE_JSON = user_data_path("investment_market_cache.json")
CURRENCIES_JSON = user_data_path("currencies.json")


def ensure_runtime_directories() -> None:
    """Create external app-data folders and, when a user is active, that user's folders."""
    for folder in (DATA_HOME, DATA_DIR, SYSTEM_DIR, USERS_DIR, BACKUPS_DIR, UPDATES_DIR, UPDATE_INBOX_DIR, GLOBAL_CACHE_DIR):
        folder.mkdir(exist_ok=True, parents=True)

    user_id = get_current_user_id()
    if user_id:
        from money_manager.users.user_manager import ensure_user_data_folder

        ensure_user_data_folder(user_id, create_files=True)
