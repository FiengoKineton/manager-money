from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

CACHE_REGISTRY_VERSION = 4
DEFAULT_TTL_SECONDS = 15 * 60
LONG_TTL_SECONDS = 60 * 60
SHORT_TTL_SECONDS = 5 * 60


@dataclass(frozen=True)
class CacheDefinition:
    name: str
    version: str
    description: str
    dependencies: tuple[str, ...] = ()
    ttl_seconds: int | None = DEFAULT_TTL_SECONDS
    sensitive: bool = True
    encrypted: bool = True
    disk_cache_allowed: bool = True
    request_cache_allowed: bool = True
    rebuild_import_path: str = ""
    invalidation_triggers: tuple[str, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)


def _def(
    name: str,
    version: str,
    description: str,
    dependencies: tuple[str, ...],
    *,
    ttl: int | None = DEFAULT_TTL_SECONDS,
    sensitive: bool = True,
    encrypted: bool = True,
    rebuild: str = "",
    request: bool = True,
    disk: bool = True,
) -> CacheDefinition:
    return CacheDefinition(
        name=name,
        version=version,
        description=description,
        dependencies=dependencies,
        ttl_seconds=ttl,
        sensitive=sensitive,
        encrypted=encrypted,
        disk_cache_allowed=disk,
        request_cache_allowed=request,
        rebuild_import_path=rebuild,
        invalidation_triggers=dependencies,
    )


CACHE_DEFINITIONS: dict[str, CacheDefinition] = {
    # Core/dashboard
    "dashboard_overview": _def("dashboard_overview", "v4", "Overview/dashboard context.", ("transactions", "ledger", "accounts", "payment_methods", "pending", "recurring", "debts", "investments"), rebuild="money_manager.services.dashboard_calculation_service.get_dashboard_overview_uncached"),
    "overview.context": _def("overview.context", "v3", "Home/overview context.", ("transactions", "ledger", "accounts", "payment_methods", "pending", "recurring", "debts", "payables", "receivables", "investments"), rebuild="money_manager.services.overview_service._build_overview_context_uncached"),
    "quick_overview": _def("quick_overview", "v4", "Small fast overview cards.", ("transactions", "ledger", "accounts", "pending"), ttl=SHORT_TTL_SECONDS, rebuild="money_manager.services.dashboard_calculation_service.get_quick_overview_uncached"),
    "transactions.load_all": _def("transactions.load_all", "v4", "Normalized enriched transaction dataframe.", ("transactions", "accounts", "payment_methods", "internal_transfers", "credit_settlements"), ttl=None),
    "transaction_initial_conditions": _def("transaction_initial_conditions", "v1", "Historical transaction totals before the rolling working window.", ("accounts", "payment_methods"), ttl=None),
    "net_explanation": _def("net_explanation", "v2", "Net-worth explanation context.", ("transactions", "ledger", "accounts", "payment_methods", "pending", "credit_settlements")),
    "transaction_table_view": _def("transaction_table_view", "v3", "Prepared transaction table rows.", ("transactions", "accounts", "payment_methods"), ttl=SHORT_TTL_SECONDS),
    "transaction_filter_options": _def("transaction_filter_options", "v1", "Transaction filter category/type options.", ("transactions", "categories"), ttl=LONG_TTL_SECONDS),
    "analysis_metrics": _def("analysis_metrics", "v2", "Analysis cockpit metrics.", ("transactions", "ledger", "accounts", "payment_methods", "pending", "recurring", "debts", "payables", "receivables", "investments"), ttl=DEFAULT_TTL_SECONDS),

    "phone.experience.summary": _def("phone.experience.summary", "v2", "Fast phone home summary.", ("transactions", "pending", "recurring", "debts", "payables"), ttl=SHORT_TTL_SECONDS),
    # Accounts/payment
    "account_balances": _def("account_balances", "v2", "Account balance rows.", ("transactions", "ledger", "accounts", "payment_methods", "internal_transfers", "credit_settlements"), rebuild="money_manager.services.account_calculation_service.get_account_balances_uncached"),
    "account_dashboard_summary": _def("account_dashboard_summary", "v5", "Accounts page summary.", ("transactions", "ledger", "accounts", "payment_methods", "internal_transfers", "credit_settlements"), rebuild="money_manager.services.account_calculation_service.get_account_dashboard_summary_uncached"),
    "account_detail_summary": _def("account_detail_summary", "v4", "Account detail summary.", ("transactions", "ledger", "accounts", "payment_methods", "internal_transfers", "credit_settlements")),
    "scope_balance_summary": _def("scope_balance_summary", "v5", "Scoped net/pending summary for topbar and account pills.", ("transactions", "ledger", "accounts", "payment_methods", "internal_transfers", "credit_settlements", "pending", "payables", "recurring"), ttl=SHORT_TTL_SECONDS),
    "payment_method_summary": _def("payment_method_summary", "v1", "Payment method usage summary.", ("transactions", "payment_methods", "accounts", "ledger"), rebuild="money_manager.services.account_calculation_service.get_payment_method_summary_uncached"),
    "payment_method_options": _def("payment_method_options", "v1", "Payment method form options.", ("payment_methods", "accounts", "profile", "preferences"), ttl=LONG_TTL_SECONDS),
    "credit_settlement_summary": _def("credit_settlement_summary", "v1", "Credit settlement summary.", ("credit_settlements", "ledger", "pending", "transactions", "accounts")),
    "internal_transfer_summary": _def("internal_transfer_summary", "v2", "Internal-transfer summary.", ("internal_transfers", "ledger", "accounts")),

    # Planning/support
    "pending_summary": _def("pending_summary", "v1", "Pending payments summary.", ("pending", "transactions", "accounts", "payment_methods")),
    "recurring_summary": _def("recurring_summary", "v1", "Recurring items summary.", ("recurring", "transactions")),
    "payables_summary": _def("payables_summary", "v1", "Payables summary.", ("payables", "transactions", "contacts")),
    "receivables_summary": _def("receivables_summary", "v1", "Receivables summary.", ("receivables", "transactions", "contacts")),
    "debts_summary": _def("debts_summary", "v1", "Debts summary.", ("debts", "debt_rules", "transactions", "contacts")),
    "parent_support_summary": _def("parent_support_summary", "v1", "Parent support summary.", ("parent_support", "parent_support_rules", "transactions")),
    "expense_projects_summary": _def("expense_projects_summary", "v1", "Expense projects summary.", ("expense_projects", "expense_project_movements", "expense_project_planned_items", "transactions")),
    "forecast_summary": _def("forecast_summary", "v1", "Forecast summary.", ("transactions", "pending", "recurring", "payables", "receivables", "debts")),

    # Wealth/analysis
    "investment_summary": _def("investment_summary", "v1", "Investment summary.", ("investments", "investment_assets", "investment_market_cache")),
    "investment_habit_snapshot": _def("investment_habit_snapshot", "v1", "Investment habit snapshot.", ("investments", "investment_assets", "investment_market_cache"), rebuild="money_manager.services.investment_service.investment_habit_snapshot"),
    "yearly_summary": _def("yearly_summary", "v1", "Yearly financial summary.", ("transactions", "ledger", "pending", "recurring", "debts", "payables", "receivables", "internal_transfers", "investments"), ttl=LONG_TTL_SECONDS, rebuild="money_manager.services.analysis_calculation_service.get_yearly_summary_uncached"),
    "category_summary": _def("category_summary", "v2", "Category summary.", ("transactions", "categories", "accounts", "payment_methods"), rebuild="money_manager.services.analysis_calculation_service.get_category_summary_uncached"),
    "monthly_summary": _def("monthly_summary", "v2", "Monthly summary.", ("transactions", "accounts", "payment_methods"), rebuild="money_manager.services.analysis_calculation_service.get_monthly_summary_uncached"),
    "payment_method_breakdown": _def("payment_method_breakdown", "v1", "Payment method breakdown.", ("transactions", "payment_methods", "accounts"), rebuild="money_manager.services.analysis_calculation_service.get_payment_method_breakdown_uncached"),
    "account_breakdown": _def("account_breakdown", "v2", "Account breakdown.", ("transactions", "accounts", "ledger"), rebuild="money_manager.services.analysis_calculation_service.get_account_breakdown_uncached"),

    # User/app context
    "profile_context": _def("profile_context", "v2", "Profile settings context.", ("profile", "accounts", "payment_methods"), ttl=LONG_TTL_SECONDS),
    "preferences_context": _def("preferences_context", "v2", "Preferences context.", ("preferences",), ttl=LONG_TTL_SECONDS),
    "navigation_context": _def("navigation_context", "v2", "Navigation context.", ("navigation", "preferences"), ttl=LONG_TTL_SECONDS, sensitive=False, encrypted=False),
    "i18n_language_file": _def("i18n_language_file", "v1", "Loaded i18n language file.", ("i18n", "preferences"), ttl=LONG_TTL_SECONDS, sensitive=False, encrypted=False),
    "documents_summary": _def("documents_summary", "v1", "Documents registry summary.", ("documents", "document_types")),
    "contacts_summary": _def("contacts_summary", "v1", "Contacts summary.", ("contacts",)),
    "integrity_summary": _def("integrity_summary", "v1", "Integrity validation summary.", ("integrity", "transactions", "ledger", "accounts", "payment_methods", "schema"), ttl=SHORT_TTL_SECONDS),
}


def get_cache_definition(name: str) -> CacheDefinition:
    definition = CACHE_DEFINITIONS.get(str(name))
    if definition is None:
        # Dynamic compatibility definition for legacy keys. These entries are
        # conservative: they depend on all money data and are sensitive.
        return CacheDefinition(
            name=str(name),
            version="legacy-v1",
            description=f"Compatibility cache entry for {name}.",
            dependencies=("transactions", "money_rows", "accounts", "payment_methods", "profile", "preferences"),
            ttl_seconds=DEFAULT_TTL_SECONDS,
            sensitive=True,
            encrypted=True,
            disk_cache_allowed=True,
            request_cache_allowed=True,
            rebuild_import_path="",
            invalidation_triggers=("transactions", "money_rows", "accounts", "payment_methods", "profile", "preferences"),
        )
    return definition


def cache_definitions() -> list[CacheDefinition]:
    return list(CACHE_DEFINITIONS.values())


def dependency_names() -> set[str]:
    names: set[str] = set()
    for definition in CACHE_DEFINITIONS.values():
        names.update(definition.dependencies)
    return names
