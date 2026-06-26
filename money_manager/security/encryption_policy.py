from __future__ import annotations

from money_manager.security.encryption_service import MAGIC_BYTES, MAGIC_TEXT

ENCRYPTION_DEFAULT_ENABLED = True
ENCRYPTION_REQUIRED_FOR_USER_DATA = True
ALLOW_PLAINTEXT_USER_DATA = False
ALLOW_TEMP_DECRYPTED_EXPORT = True
TEMP_EXPORT_TTL_MINUTES = 10

# User-data files that contain personal/financial information and must be
# written through the secure storage layer when encryption is enabled.
SENSITIVE_USER_FILE_NAMES = {
    "accounts.json",
    "payment_methods.json",
    "profile.json",
    "preferences.json",
    "categories.json",
    "contacts.json",
    "navigation.json",
    "document_types.json",
    "currencies.json",
    "notification_state.json",
    "account_events.json",
    "expenses.csv",
    "incomes.csv",
    "investments.csv",
    "investment_assets.csv",
    "investment_market_cache.json",
    "pending.csv",
    "recurring.csv",
    "payables.csv",
    "receivables.csv",
    "debts.csv",
    "debt_rules.csv",
    "parent_support.csv",
    "parent_support_rules.csv",
    "expense_projects.csv",
    "expense_project_movements.csv",
    "expense_project_planned_items.csv",
    "account_ledger.csv",
    "credit_settlements.csv",
    "internal_transfers.csv",
    "receipts.json",
    "discount_balances.json",
    "sparagnat_fottut.csv",
    "documents/_metadata.json",
}

SENSITIVE_USER_DIR_PREFIXES = (
    "documents/",
    "profile/",
)

DISPOSABLE_SENSITIVE_CACHE_DIRS = (
    "cache",
)


def is_sensitive_user_relative_path(relative_path: str) -> bool:
    normalized = str(relative_path or "").replace("\\", "/").strip("/")
    if not normalized:
        return False
    if normalized in SENSITIVE_USER_FILE_NAMES:
        return True
    return any(normalized.startswith(prefix) for prefix in SENSITIVE_USER_DIR_PREFIXES)
