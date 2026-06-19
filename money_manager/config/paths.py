from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
DOCUMENTS_DIR = PROJECT_ROOT / "documents"
PLOTS_DIR = PROJECT_ROOT / "static" / "plots"
CACHE_DIR = DATA_DIR / "cache"
NOTIFICATIONS_STATE_JSON = DATA_DIR / "notification_state.json"

TRANSACTION_FILES = {
    "expense": DATA_DIR / "expenses.csv",
    "income": DATA_DIR / "incomes.csv",
    "investment": DATA_DIR / "investments.csv",
}

PENDING_CSV = DATA_DIR / "pending.csv"
INTERNAL_TRANSFERS_CSV = DATA_DIR / "internal_transfers.csv"
RECURRING_CSV = DATA_DIR / "recurring.csv"
SPARAGNAT_CSV = DATA_DIR / "sparagnat_fottut.csv"
PARENT_SUPPORT_CSV = DATA_DIR / "parent_support.csv"
PARENT_SUPPORT_RULES_CSV = DATA_DIR / "parent_support_rules.csv"
DEBTS_CSV = DATA_DIR / "debts.csv"
DEBT_RULES_CSV = DATA_DIR / "debt_rules.csv"
RECEIVABLES_CSV = DATA_DIR / "receivables.csv"
PAYABLES_CSV = DATA_DIR / "payables.csv"
EXPENSE_PROJECTS_CSV = DATA_DIR / "expense_projects.csv"
EXPENSE_PROJECT_MOVEMENTS_CSV = DATA_DIR / "expense_project_movements.csv"
EXPENSE_PROJECT_PLANNED_ITEMS_CSV = DATA_DIR / "expense_project_planned_items.csv"
INVESTMENT_ASSETS_CSV = DATA_DIR / "investment_assets.csv"
INVESTMENT_MARKET_CACHE_JSON = DATA_DIR / "investment_market_cache.json"
CURRENCIES_JSON = DATA_DIR / "currencies.json"

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


def ensure_runtime_directories() -> None:
    """Create folders the app needs at runtime."""
    DATA_DIR.mkdir(exist_ok=True, parents=True)
    DOCUMENTS_DIR.mkdir(exist_ok=True, parents=True)
    PLOTS_DIR.mkdir(exist_ok=True, parents=True)
    CACHE_DIR.mkdir(exist_ok=True, parents=True)

    for folder in DOCUMENT_FOLDERS:
        (DOCUMENTS_DIR / folder).mkdir(exist_ok=True, parents=True)
