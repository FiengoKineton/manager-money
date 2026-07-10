"""Central registry for the desktop navigation sidebar.

The visible sidebar and the Profile > Customise navigation editor both consume
this structure. User preferences store only hidden page IDs, ordering, and the
default collapsed state; routes remain registered even when a link is hidden.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable


def _item(
    page_id: str,
    endpoint: str,
    label: str,
    icon: str,
    order: int,
    *,
    active_endpoints: Iterable[str] | None = None,
    preserve_account_scope: bool = False,
) -> dict[str, Any]:
    return {
        "page_id": page_id,
        "endpoint": endpoint,
        "label": label,
        "icon": icon,
        "default_visible": True,
        "default_order": order,
        "active_endpoints": list(active_endpoints or [endpoint]),
        "preserve_account_scope": bool(preserve_account_scope),
    }


def _subgroup(
    subgroup_id: str,
    label: str,
    icon: str,
    order: int,
    items: list[dict[str, Any]],
    *,
    default_open: bool = False,
) -> dict[str, Any]:
    return {
        "subgroup_id": subgroup_id,
        "label": label,
        "icon": icon,
        "default_order": order,
        "default_open": bool(default_open),
        "items": items,
    }


DEFAULT_NAVIGATION: list[dict[str, Any]] = [
    {
        "group_id": "accounts",
        "label": "Conti Correnti",
        "icon": "🏦",
        "default_open": False,
        "default_order": 10,
        "items": [],
        "subgroups": [
            _subgroup(
                "accounts_all",
                "All Conti",
                "🏠",
                10,
                [
                    _item(
                        "accounts",
                        "accounts.accounts_page",
                        "All Conti",
                        "🏦",
                        10,
                        active_endpoints=["accounts.accounts_page", "accounts.account_detail", "accounts.account_payment_method_detail"],
                    ),
                    _item(
                        "transactions",
                        "transactions.transactions_page",
                        "Transactions",
                        "↕",
                        20,
                        active_endpoints=[
                            "transactions.transactions_page",
                            "transactions.transaction_detail",
                            "transactions.add_transaction",
                            "transactions.edit_transaction",
                        ],
                    ),
                ],
            ),
            _subgroup(
                "accounts_transfers",
                "Transfers",
                "⇄",
                20,
                [
                    _item("internal_transfers", "internal_transfers.internal_transfers_page", "Internal transfers", "⇄", 10),
                    _item(
                        "bonifico",
                        "bonifico.bonifico_page",
                        "Bonifico",
                        "🏦",
                        20,
                        active_endpoints=["bonifico.bonifico_page", "bonifico.contacts_search_api"],
                    ),
                ],
            ),
            _subgroup(
                "accounts_tools",
                "Contacts & tools",
                "🧰",
                30,
                [
                    _item(
                        "contacts",
                        "contacts.contacts_page",
                        "Contacts",
                        "👤",
                        10,
                        active_endpoints=[
                            "contacts.contacts_page",
                            "contacts.new_contact",
                            "contacts.contact_detail",
                            "contacts.edit_contact",
                        ],
                    ),
                    _item("currencies", "currencies.currencies_page", "Currency exchange", "💱", 20),
                    _item("discount_balances", "discount_balances.discount_balances_page", "Gift cards & buoni", "🎟️", 30),
                    _item("reconciliation", "reconciliation.reconciliation_page", "Reconciliation", "✓", 40),
                ],
            ),
            _subgroup(
                "accounts_records",
                "Records & support",
                "🗂️",
                40,
                [
                    _item("documents", "documents.documents", "Documents", "📄", 10),
                    _item("sparagnat", "sparagnat.sparagnat_page", "Sparagnat e Fottut", "🧾", 20),
                    _item("parent_support", "parent_support.parent_support_page", "Parent Support", "👪", 30),
                ],
            ),
        ],
    },
    {
        "group_id": "planning",
        "label": "Planning",
        "icon": "📅",
        "default_open": False,
        "default_order": 20,
        "items": [],
        "subgroups": [
            _subgroup(
                "planning_monthly",
                "Monthly planning",
                "◴",
                10,
                [
                    _item("financial_calendar", "financial_calendar.calendar_page", "Calendar", "📅", 10),
                    _item("notifications_center", "notifications.center", "Alerts center", "🔔", 20),
                    _item("pending_payments", "pending.pending_page", "Pending", "◴", 30),
                    _item("recurring_rules", "pending.recurring_page", "Recurring", "↻", 40),
                ],
            ),
            _subgroup(
                "planning_common",
                "Common flows",
                "↻",
                20,
                [
                    _item("bills", "managed_recurring.bills_page", "Bollette", "💡", 10),
                    _item("work_income", "managed_recurring.work_income_page", "Stipendi / Cedolini", "💼", 20),
                    _item("automation", "automation.automation_page", "Smart automation", "⚙", 30),
                ],
            ),
            _subgroup(
                "planning_obligations",
                "Loans & obligations",
                "−",
                30,
                [
                    _item("mortgages", "mortgages.mortgages_page", "Mutui", "🏠", 10),
                    _item("payables", "payables.payables_page", "Payables", "🧾", 20),
                    _item("debts", "debts.debts_page", "Debts", "−", 30),
                    _item("receivables", "receivables.receivables_page", "Receivables", "＋", 40),
                ],
            ),
            _subgroup(
                "planning_projects",
                "Projects & goals",
                "◎",
                40,
                [
                    _item("planned_expenses", "planned_expenses.planned_expenses_page", "Planned expenses", "🧾", 10),
                    _item("savings_goals", "savings_goals.savings_goals_page", "Savings goals", "◎", 20),
                    _item(
                        "expense_projects",
                        "expense_projects.expense_projects_page",
                        "Projects",
                        "▤",
                        30,
                        active_endpoints=["expense_projects.expense_projects_page", "expense_projects.expense_project_detail"],
                    ),
                    _item("forecast", "forecast.forecast", "Forecast", "↗", 40),
                ],
            ),
        ],
    },
    {
        "group_id": "analysis",
        "label": "Analysis & wealth",
        "icon": "📊",
        "default_open": False,
        "default_order": 30,
        "subgroups": [],
        "items": [
            _item("dashboard", "dashboard.index", "Overview", "📌", 10, preserve_account_scope=True),
            _item("analysis", "analysis.analysis", "Analysis", "📊", 20),
            _item("investments", "investments.investments_page", "Investments", "📈", 30),
            _item("yearly_summary", "yearly_summary.yearly_summary_page", "Yearly summary", "🗓️", 40),
        ],
    },
]


def navigation_registry() -> list[dict[str, Any]]:
    return deepcopy(DEFAULT_NAVIGATION)


def _all_items() -> Iterable[dict[str, Any]]:
    for group in DEFAULT_NAVIGATION:
        yield from group.get("items", [])
        for subgroup in group.get("subgroups", []):
            yield from subgroup.get("items", [])


def registry_page_ids() -> set[str]:
    return {str(item.get("page_id") or "") for item in _all_items() if item.get("page_id")}


def registry_group_ids() -> set[str]:
    return {str(group.get("group_id") or "") for group in DEFAULT_NAVIGATION if group.get("group_id")}


def registry_subgroup_ids() -> set[str]:
    return {
        str(subgroup.get("subgroup_id") or "")
        for group in DEFAULT_NAVIGATION
        for subgroup in group.get("subgroups", [])
        if subgroup.get("subgroup_id")
    }
