from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Callable, Literal

from money_manager.config.user_defaults import default_for
from money_manager.domain.constants import (
    ACCOUNT_LEDGER_FIELDS,
    CREDIT_SETTLEMENT_FIELDS,
    DEBT_FIELDS,
    DEBT_RULE_FIELDS,
    EXPENSE_PROJECT_FIELDS,
    EXPENSE_PROJECT_MOVEMENT_FIELDS,
    EXPENSE_PROJECT_PLANNED_ITEM_FIELDS,
    INTERNAL_TRANSFER_FIELDS,
    INVESTMENT_ASSET_FIELDS,
    PARENT_SUPPORT_FIELDS,
    PARENT_SUPPORT_RULE_FIELDS,
    PAYABLE_FIELDS,
    PENDING_FIELDS,
    RECEIVABLE_FIELDS,
    RECURRING_FIELDS,
    SPARAGNAT_FIELDS,
    TRANSACTION_FIELDS,
)

Scope = Literal["system", "user", "app_config", "global_cache"]
FileType = Literal["json", "csv", "directory", "binary_folder"]
BackupPolicy = Literal["include", "exclude", "include_optional"]
EncryptionPolicy = Literal["none", "optional", "required"]
SensitiveLevel = Literal["public", "personal", "financial", "secret"]


def _deepcopy_factory(payload: Any) -> Callable[[], Any]:
    def factory() -> Any:
        return deepcopy(payload)
    return factory


def _config_default(filename: str) -> Callable[[], Any]:
    def factory() -> Any:
        return default_for(filename)
    return factory


@dataclass(frozen=True)
class DataFileDefinition:
    name: str
    scope: Scope
    relative_path: str
    file_type: FileType
    schema_version: int = 1
    csv_fields: tuple[str, ...] = ()
    required_columns: tuple[str, ...] = ()
    optional_columns: tuple[str, ...] = ()
    preserve_unknown_columns: bool = True
    default_factory: Callable[[], Any] | None = None
    backup_policy: BackupPolicy = "include"
    cache_policy: str = "none"
    invalidation_tags: tuple[str, ...] = ()
    encryption_policy: EncryptionPolicy = "none"
    sensitive_level: SensitiveLevel = "personal"
    encrypted_by_default: bool = False
    description: str = ""
    migration_handler: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def path_parts(self) -> tuple[str, ...]:
        return PurePosixPath(self.relative_path).parts

    def default_content(self) -> Any:
        if self.default_factory is None:
            return None
        return self.default_factory()


def _csv(name: str, filename: str, fields: list[str], *, description: str, sensitive: SensitiveLevel = "financial", encrypted_by_default: bool = True) -> DataFileDefinition:
    return DataFileDefinition(
        name=name,
        scope="user",
        relative_path=filename,
        file_type="csv",
        schema_version=1,
        csv_fields=tuple(fields),
        required_columns=tuple(fields),
        preserve_unknown_columns=True,
        backup_policy="include",
        cache_policy="invalidate_on_write",
        invalidation_tags=(name, "money_rows"),
        encryption_policy="required" if encrypted_by_default else "optional",
        sensitive_level=sensitive,
        encrypted_by_default=encrypted_by_default,
        description=description,
    )


def _json(name: str, filename: str, default: Callable[[], Any] | dict[str, Any], *, description: str, sensitive: SensitiveLevel = "personal", backup: BackupPolicy = "include", cache: str = "invalidate_on_write", encrypted_by_default: bool = False) -> DataFileDefinition:
    return DataFileDefinition(
        name=name,
        scope="user",
        relative_path=filename,
        file_type="json",
        schema_version=1,
        default_factory=default if callable(default) else _deepcopy_factory(default),
        backup_policy=backup,
        cache_policy=cache,
        invalidation_tags=(name,),
        encryption_policy="required" if encrypted_by_default else "optional",
        sensitive_level=sensitive,
        encrypted_by_default=encrypted_by_default,
        description=description,
    )


DATA_REGISTRY_VERSION = 1

SYSTEM_DEFINITIONS: tuple[DataFileDefinition, ...] = (
    DataFileDefinition(
        name="system_users",
        scope="system",
        relative_path="users.json",
        file_type="json",
        schema_version=1,
        default_factory=_deepcopy_factory({"schema_version": 1, "users": []}),
        backup_policy="exclude",
        encryption_policy="none",
        sensitive_level="secret",
        encrypted_by_default=False,
        description="System login registry with user IDs and password hashes; intentionally plaintext so login can work before vault unlock.",
    ),
)

APP_CONFIG_DEFINITIONS: tuple[DataFileDefinition, ...] = (
    DataFileDefinition(
        name="local_app",
        scope="app_config",
        relative_path="local_app.json",
        file_type="json",
        schema_version=1,
        default_factory=_deepcopy_factory({"schema_version": 1}),
        backup_policy="include_optional",
        encryption_policy="none",
        sensitive_level="personal",
        description="Machine-local install paths and update source settings.",
    ),
    DataFileDefinition(
        name="install_state",
        scope="app_config",
        relative_path="install_state.json",
        file_type="json",
        schema_version=1,
        default_factory=_deepcopy_factory({"schema_version": 1, "history": []}),
        backup_policy="include_optional",
        encryption_policy="none",
        sensitive_level="personal",
        description="Installed version, schema version, staged update, rollback metadata, and update history.",
    ),
)

USER_JSON_DEFINITIONS: tuple[DataFileDefinition, ...] = (
    _json("profile", "profile.json", _config_default("profile.json"), description="Personal profile and user-level defaults.", sensitive="personal", encrypted_by_default=True),
    _json("preferences", "preferences.json", _config_default("preferences.json"), description="Theme, language, currency, privacy, and onboarding preferences.", sensitive="personal", encrypted_by_default=True),
    _json("categories", "categories.json", _config_default("categories.json"), description="Custom and hidden transaction categories.", sensitive="personal", encrypted_by_default=True),
    _json("accounts", "accounts.json", _config_default("accounts.json"), description="Balance containers, current accounts, dependent wallets, credit-card liabilities, and account policy.", sensitive="financial", encrypted_by_default=True),
    _json("payment_methods", "payment_methods.json", _config_default("payment_methods.json"), description="Payment channels and their linked account/funding/settlement rules.", sensitive="financial", encrypted_by_default=True),
    _json("contacts", "contacts.json", _config_default("contacts.json"), description="People and company contacts for transfer-style movements.", sensitive="personal", encrypted_by_default=True),
    _json("navigation", "navigation.json", _config_default("navigation.json"), description="Per-user sidebar visibility and ordering preferences.", sensitive="personal"),
    _json("document_types", "document_types.json", _config_default("document_types.json"), description="Document folders/types visible in the document registry.", sensitive="personal", encrypted_by_default=True),
    _json("currencies", "currencies.json", {}, description="Currency settings and exchange-rate metadata.", sensitive="personal"),
    _json("notification_state", "notification_state.json", {"version": 1, "read": {}, "history": []}, description="Read/unread notification state.", sensitive="personal", backup="include_optional"),
    _json("investment_market_cache", "investment_market_cache.json", {"symbols": {}, "last_refresh_attempt": ""}, description="Market-data cache for investment views.", sensitive="financial", backup="exclude", cache="cache_file"),
    _json("account_events", "account_events.json", {"schema_version": 1, "events": []}, description="Account lifecycle and closure/replacement event log.", sensitive="financial", encrypted_by_default=True),
    _json("documents_metadata", "documents/_metadata.json", {"schema_version": 1, "documents": []}, description="Document registry metadata.", sensitive="personal", encrypted_by_default=True),
    _json("receipts", "receipts.json", {"schema_version": 1, "receipts": {}, "updated_at": ""}, description="Transaction receipt/shopping-list metadata.", sensitive="financial", encrypted_by_default=True),
    _json("discount_balances", "discount_balances.json", {"schema_version": 1, "sources": [], "events": [], "updated_at": ""}, description="Gift-card and buono-sconto balances used as receipt discounts.", sensitive="financial", encrypted_by_default=True),
)

USER_CSV_DEFINITIONS: tuple[DataFileDefinition, ...] = (
    _csv("expenses", "expenses.csv", TRANSACTION_FIELDS, description="Expense transactions."),
    _csv("incomes", "incomes.csv", TRANSACTION_FIELDS, description="Income transactions."),
    _csv("investments", "investments.csv", TRANSACTION_FIELDS, description="Investment transaction rows."),
    _csv("investment_assets", "investment_assets.csv", INVESTMENT_ASSET_FIELDS, description="Investment asset metadata."),
    _csv("pending", "pending.csv", PENDING_FIELDS, description="Scheduled and pending payments."),
    _csv("recurring", "recurring.csv", RECURRING_FIELDS, description="Recurring transaction rules."),
    _csv("debts", "debts.csv", DEBT_FIELDS, description="Debts the user owes."),
    _csv("debt_rules", "debt_rules.csv", DEBT_RULE_FIELDS, description="Debt automation rules."),
    _csv("payables", "payables.csv", PAYABLE_FIELDS, description="Payables / bills owed by the user."),
    _csv("receivables", "receivables.csv", RECEIVABLE_FIELDS, description="Receivables owed to the user."),
    _csv("parent_support", "parent_support.csv", PARENT_SUPPORT_FIELDS, description="Parent support rows."),
    _csv("parent_support_rules", "parent_support_rules.csv", PARENT_SUPPORT_RULE_FIELDS, description="Parent support automation rules."),
    _csv("expense_projects", "expense_projects.csv", EXPENSE_PROJECT_FIELDS, description="Expense project containers."),
    _csv("expense_project_movements", "expense_project_movements.csv", EXPENSE_PROJECT_MOVEMENT_FIELDS, description="Expense project movements."),
    _csv("expense_project_planned_items", "expense_project_planned_items.csv", EXPENSE_PROJECT_PLANNED_ITEM_FIELDS, description="Planned expense project items."),
    _csv("internal_transfers", "internal_transfers.csv", INTERNAL_TRANSFER_FIELDS, description="Internal transfers between accounts."),
    _csv("account_ledger", "account_ledger.csv", ACCOUNT_LEDGER_FIELDS, description="Double-entry-style account balance movements."),
    _csv("credit_settlements", "credit_settlements.csv", CREDIT_SETTLEMENT_FIELDS, description="Credit statement and settlement records."),
    _csv("sparagnat", "sparagnat_fottut.csv", SPARAGNAT_FIELDS, description="Sparagnat Fottut records."),
)

USER_FOLDER_DEFINITIONS: tuple[DataFileDefinition, ...] = (
    DataFileDefinition("documents", "user", "documents", "binary_folder", backup_policy="include", encryption_policy="required", sensitive_level="personal", encrypted_by_default=True, description="User uploaded documents."),
    DataFileDefinition("plots", "user", "plots", "binary_folder", backup_policy="exclude", cache_policy="generated", encryption_policy="none", sensitive_level="public", description="Generated plots; excluded from backup."),
    DataFileDefinition("cache", "user", "cache", "directory", backup_policy="exclude", cache_policy="cache_folder", encryption_policy="none", sensitive_level="personal", description="Compatibility user cache folder. Prompt 14 will move cache under global data cache."),
    DataFileDefinition("user_backups", "user", "backups", "binary_folder", backup_policy="exclude", encryption_policy="optional", sensitive_level="financial", description="Per-user backup ZIPs; not included inside backups."),
)

GLOBAL_CACHE_DEFINITIONS: tuple[DataFileDefinition, ...] = (
    DataFileDefinition("global_cache", "global_cache", "", "directory", backup_policy="exclude", cache_policy="cache_folder", encryption_policy="none", sensitive_level="personal", description="External app cache root."),
)

ALL_DEFINITIONS: tuple[DataFileDefinition, ...] = (
    *SYSTEM_DEFINITIONS,
    *APP_CONFIG_DEFINITIONS,
    *USER_JSON_DEFINITIONS,
    *USER_CSV_DEFINITIONS,
    *USER_FOLDER_DEFINITIONS,
    *GLOBAL_CACHE_DEFINITIONS,
)

_BY_NAME = {definition.name: definition for definition in ALL_DEFINITIONS}
_BY_USER_RELATIVE = {definition.relative_path: definition for definition in ALL_DEFINITIONS if definition.scope == "user"}


def all_definitions(scope: Scope | None = None) -> list[DataFileDefinition]:
    if scope is None:
        return list(ALL_DEFINITIONS)
    return [definition for definition in ALL_DEFINITIONS if definition.scope == scope]


def definition_by_name(name: str) -> DataFileDefinition | None:
    return _BY_NAME.get(name)


def user_file_definitions() -> list[DataFileDefinition]:
    return all_definitions("user")


def user_csv_definitions() -> list[DataFileDefinition]:
    return [definition for definition in USER_CSV_DEFINITIONS]


def user_json_definitions() -> list[DataFileDefinition]:
    return [definition for definition in USER_JSON_DEFINITIONS]


def flat_migration_filenames() -> list[str]:
    return [definition.relative_path for definition in ALL_DEFINITIONS if definition.scope == "user" and definition.file_type in {"csv", "json"} and "/" not in definition.relative_path]


def csv_schemas() -> dict[str, list[str]]:
    return {definition.relative_path: list(definition.csv_fields) for definition in USER_CSV_DEFINITIONS}


def json_defaults() -> dict[str, Any]:
    return {definition.relative_path: definition.default_content() for definition in USER_JSON_DEFINITIONS if definition.default_factory is not None and "/" not in definition.relative_path}


def encrypted_user_definitions() -> list[DataFileDefinition]:
    return [definition for definition in all_definitions("user") if getattr(definition, "encrypted_by_default", False)]


def definition_for_filename(filename: str) -> DataFileDefinition | None:
    normalized = str(filename or "").replace("\\", "/").strip("/")
    return _BY_USER_RELATIVE.get(normalized) or definition_by_name(normalized)
