from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
DOCUMENTS_DIR = PROJECT_ROOT / "documents"
PLOTS_DIR = PROJECT_ROOT / "static" / "plots"

TRANSACTION_FILES = {
    "expense": DATA_DIR / "expenses.csv",
    "income": DATA_DIR / "incomes.csv",
    "investment": DATA_DIR / "investments.csv",
}

PENDING_CSV = DATA_DIR / "pending.csv"
RECURRING_CSV = DATA_DIR / "recurring.csv"
SPARAGNAT_CSV = DATA_DIR / "sparagnat_fottut.csv"
PARENT_SUPPORT_CSV = DATA_DIR / "parent_support.csv"
PARENT_SUPPORT_RULES_CSV = DATA_DIR / "parent_support_rules.csv"
DEBTS_CSV = DATA_DIR / "debts.csv"
DEBT_RULES_CSV = DATA_DIR / "debt_rules.csv"

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

    for folder in DOCUMENT_FOLDERS:
        (DOCUMENTS_DIR / folder).mkdir(exist_ok=True, parents=True)
