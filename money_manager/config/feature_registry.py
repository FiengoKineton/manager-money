"""Feature-level map of the Money Manager app.

This registry is intentionally descriptive.  It gives future changes one place
where a developer can see which route, service, repository, template, and data
files belong to each feature without moving existing files or changing runtime
behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


@dataclass(frozen=True)
class FeatureSpec:
    """Documentation object for one app feature."""

    key: str
    group: str
    label: str
    route_module: str
    blueprint: str
    service_modules: tuple[str, ...] = field(default_factory=tuple)
    repository_modules: tuple[str, ...] = field(default_factory=tuple)
    templates: tuple[str, ...] = field(default_factory=tuple)
    data_keys: tuple[str, ...] = field(default_factory=tuple)
    notes: str = ""


FEATURE_GROUPS: dict[str, dict[str, str]] = {
    "core": {
        "label": "Core",
        "description": "Overview, dashboard, transaction log, and analysis views.",
    },
    "planning": {
        "label": "Planning",
        "description": "Future or expected money movements: pending, recurring, debts, payables, and projects.",
    },
    "accounts": {
        "label": "Accounts",
        "description": "Liquid-account balances, internal transfers, currencies, and account-related support trackers.",
    },
    "assets": {
        "label": "Assets",
        "description": "Investment positions and market snapshots.",
    },
    "support": {
        "label": "Support & Documents",
        "description": "Receivables, family/support trackers, documents, and special-purpose records.",
    },
}


FEATURES: dict[str, FeatureSpec] = {
    "overview": FeatureSpec(
        key="overview",
        group="core",
        label="Quick/Detailed Overview",
        route_module="money_manager.web.routes.dashboard",
        blueprint="dashboard",
        service_modules=("money_manager.services.overview_service",),
        repository_modules=("money_manager.repositories.transactions", "money_manager.repositories.pending"),
        templates=("overview_simple.html", "overview.html"),
        data_keys=("expenses", "incomes", "investments", "pending", "internal_transfers"),
        notes="Uses existing overview_service formulas. Scoped/global net remains the source of truth.",
    ),
    "dashboard": FeatureSpec(
        key="dashboard",
        group="core",
        label="Dashboard",
        route_module="money_manager.web.routes.dashboard",
        blueprint="dashboard",
        service_modules=("money_manager.services.analytics_service", "money_manager.services.transaction_service"),
        repository_modules=("money_manager.repositories.transactions",),
        templates=("index.html",),
        data_keys=("expenses", "incomes", "investments", "internal_transfers"),
        notes="Shares persistent transaction-filter state with the Transactions page.",
    ),
    "transactions": FeatureSpec(
        key="transactions",
        group="core",
        label="Transactions",
        route_module="money_manager.web.routes.transactions",
        blueprint="transactions",
        service_modules=("money_manager.services.transaction_service", "money_manager.services.quick_log_service"),
        repository_modules=("money_manager.repositories.transactions",),
        templates=("transactions.html", "transaction_detail.html", "add_transaction.html"),
        data_keys=("expenses", "incomes", "investments"),
    ),
    "analysis": FeatureSpec(
        key="analysis",
        group="core",
        label="Analysis",
        route_module="money_manager.web.routes.analysis",
        blueprint="analysis",
        service_modules=("money_manager.services.analytics_service",),
        repository_modules=("money_manager.repositories.transactions",),
        templates=("analysis.html",),
        data_keys=("expenses", "incomes", "investments", "internal_transfers"),
    ),
    "net_explanation": FeatureSpec(
        key="net_explanation",
        group="core",
        label="Net Explanation",
        route_module="money_manager.web.routes.net_explanation",
        blueprint="net_explanation",
        service_modules=("money_manager.services.net_explanation_service",),
        repository_modules=("money_manager.repositories.transactions", "money_manager.repositories.pending"),
        templates=("net_explanation.html",),
        data_keys=("expenses", "incomes", "investments", "pending", "internal_transfers"),
        notes="Read-only explanation page; it never writes or recalculates balances differently.",
    ),
    "pending": FeatureSpec(
        key="pending",
        group="planning",
        label="Pending Payments",
        route_module="money_manager.web.routes.pending",
        blueprint="pending",
        service_modules=("money_manager.services.pending_service",),
        repository_modules=("money_manager.repositories.pending",),
        templates=("pending.html",),
        data_keys=("pending", "expenses", "incomes"),
    ),
    "recurring": FeatureSpec(
        key="recurring",
        group="planning",
        label="Recurring Rules",
        route_module="money_manager.web.routes.pending",
        blueprint="pending",
        service_modules=("money_manager.services.recurring_service",),
        repository_modules=("money_manager.repositories.recurring",),
        templates=("recurring.html",),
        data_keys=("recurring_rules", "pending"),
    ),
    "forecast": FeatureSpec(
        key="forecast",
        group="planning",
        label="Forecast",
        route_module="money_manager.web.routes.forecast",
        blueprint="forecast",
        service_modules=("money_manager.services.forecast_service",),
        repository_modules=("money_manager.repositories.pending", "money_manager.repositories.recurring"),
        templates=("forecast.html",),
        data_keys=("pending", "recurring_rules", "payables", "expense_projects"),
    ),
    "debts": FeatureSpec(
        key="debts",
        group="planning",
        label="Debts I Owe",
        route_module="money_manager.web.routes.debts",
        blueprint="debts",
        service_modules=("money_manager.services.debt_service",),
        repository_modules=("money_manager.repositories.debts",),
        templates=("debts.html",),
        data_keys=("debts", "debt_rules"),
    ),
    "payables": FeatureSpec(
        key="payables",
        group="planning",
        label="Payables",
        route_module="money_manager.web.routes.payables",
        blueprint="payables",
        service_modules=("money_manager.services.payable_service",),
        repository_modules=("money_manager.repositories.payables",),
        templates=("payables.html",),
        data_keys=("payables", "expenses"),
    ),
    "expense_projects": FeatureSpec(
        key="expense_projects",
        group="planning",
        label="Expense Projects",
        route_module="money_manager.web.routes.expense_projects",
        blueprint="expense_projects",
        service_modules=("money_manager.services.expense_project_service",),
        repository_modules=("money_manager.repositories.expense_projects",),
        templates=("expense_projects.html", "expense_project_detail.html"),
        data_keys=("expense_projects", "expense_project_movements", "expense_project_planned_items"),
    ),
    "accounts": FeatureSpec(
        key="accounts",
        group="accounts",
        label="Conti Correnti",
        route_module="money_manager.web.routes.accounts",
        blueprint="accounts",
        service_modules=("money_manager.services.account_service",),
        repository_modules=("money_manager.repositories.transactions",),
        templates=("accounts.html", "account_detail.html"),
        data_keys=("accounts", "expenses", "incomes", "investments", "internal_transfers"),
    ),
    "internal_transfers": FeatureSpec(
        key="internal_transfers",
        group="accounts",
        label="Internal Transfers",
        route_module="money_manager.web.routes.internal_transfers",
        blueprint="internal_transfers",
        service_modules=("money_manager.services.internal_transfer_service",),
        repository_modules=("money_manager.repositories.internal_transfers",),
        templates=("internal_transfers.html",),
        data_keys=("internal_transfers", "accounts"),
    ),
    "currencies": FeatureSpec(
        key="currencies",
        group="accounts",
        label="Currency Exchange",
        route_module="money_manager.web.routes.currencies",
        blueprint="currencies",
        service_modules=("money_manager.services.currency_service",),
        repository_modules=(),
        templates=("currencies.html",),
        data_keys=("currencies",),
    ),
    "investments": FeatureSpec(
        key="investments",
        group="assets",
        label="Investments",
        route_module="money_manager.web.routes.investments",
        blueprint="investments",
        service_modules=("money_manager.services.investment_service",),
        repository_modules=("money_manager.repositories.investments",),
        templates=("investments.html",),
        data_keys=("investments", "investment_assets", "investment_market_cache"),
    ),
    "receivables": FeatureSpec(
        key="receivables",
        group="support",
        label="Money Owed To Me",
        route_module="money_manager.web.routes.receivables",
        blueprint="receivables",
        service_modules=("money_manager.services.receivable_service",),
        repository_modules=("money_manager.repositories.receivables",),
        templates=("receivables.html",),
        data_keys=("receivables",),
    ),
    "sparagnat": FeatureSpec(
        key="sparagnat",
        group="support",
        label="Sparagnat e Fottut",
        route_module="money_manager.web.routes.sparagnat",
        blueprint="sparagnat",
        service_modules=("money_manager.services.sparagnat_service",),
        repository_modules=("money_manager.repositories.sparagnat",),
        templates=("sparagnat.html",),
        data_keys=("sparagnat",),
    ),
    "parent_support": FeatureSpec(
        key="parent_support",
        group="support",
        label="Parent Support",
        route_module="money_manager.web.routes.parent_support",
        blueprint="parent_support",
        service_modules=("money_manager.services.parent_support_service",),
        repository_modules=("money_manager.repositories.parent_support",),
        templates=("parent_support.html",),
        data_keys=("parent_support", "parent_support_rules"),
    ),
    "documents": FeatureSpec(
        key="documents",
        group="support",
        label="Documents",
        route_module="money_manager.web.routes.documents",
        blueprint="documents",
        service_modules=("money_manager.repositories.documents",),
        repository_modules=("money_manager.repositories.documents",),
        templates=("documents.html",),
        data_keys=(),
    ),
}


def features_by_group(group: str) -> list[FeatureSpec]:
    """Return features in one group, preserving registry order."""
    return [feature for feature in FEATURES.values() if feature.group == group]


def feature_keys_for_group(group: str) -> tuple[str, ...]:
    return tuple(feature.key for feature in features_by_group(group))


def feature_table(groups: Iterable[str] | None = None) -> list[dict[str, str]]:
    """Flatten the registry for optional diagnostics/admin pages."""
    allowed = set(groups or FEATURE_GROUPS.keys())
    rows: list[dict[str, str]] = []
    for feature in FEATURES.values():
        if feature.group not in allowed:
            continue
        rows.append({
            "key": feature.key,
            "group": feature.group,
            "label": feature.label,
            "route_module": feature.route_module,
            "blueprint": feature.blueprint,
            "templates": ", ".join(feature.templates),
            "data_keys": ", ".join(feature.data_keys),
            "notes": feature.notes,
        })
    return rows
