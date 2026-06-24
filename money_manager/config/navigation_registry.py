"""Central desktop navigation registry.

The sidebar is intentionally data-driven: pages are registered here, while each
user stores only preferences such as hidden pages and custom ordering in
``data/users/{user_id}/navigation.json``. Hiding a page removes it from the
sidebar only; routes stay registered and direct URL access continues to work.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

DEFAULT_NAVIGATION: list[dict[str, Any]] = [
    {
        "group_id": "overview",
        "label_key": "nav.overview",
        "default_open": True,
        "default_order": 10,
        "items": [
            {
                "page_id": "quick_overview",
                "endpoint": "dashboard.overview",
                "label_key": "nav.quick_overview",
                "default_visible": True,
                "default_order": 10,
                "active_endpoints": ["dashboard.overview"],
            },
            {
                "page_id": "detailed_overview",
                "endpoint": "dashboard.overview_detailed",
                "label_key": "nav.detailed_overview",
                "default_visible": True,
                "default_order": 20,
                "active_endpoints": ["dashboard.overview_detailed"],
            },
            {
                "page_id": "dashboard",
                "endpoint": "dashboard.index",
                "label_key": "nav.dashboard",
                "default_visible": True,
                "default_order": 30,
                "active_endpoints": ["dashboard.index"],
            },
            {
                "page_id": "transactions",
                "endpoint": "transactions.transactions_page",
                "label_key": "nav.transactions",
                "default_visible": True,
                "default_order": 40,
                "active_endpoints": [
                    "transactions.transactions_page",
                    "transactions.transaction_detail",
                    "transactions.add_transaction",
                ],
            },
            {
                "page_id": "why_this_net",
                "endpoint": "net_explanation.net_explanation",
                "label_key": "nav.why_this_net",
                "default_visible": True,
                "default_order": 50,
                "active_endpoints": ["net_explanation.net_explanation"],
            },
        ],
    },
    {
        "group_id": "planning",
        "label_key": "nav.planning",
        "default_open": False,
        "default_order": 30,
        "items": [
            {
                "page_id": "pending_payments",
                "endpoint": "pending.pending_page",
                "label_key": "nav.pending_payments",
                "section_label_key": "nav.scheduled_money",
                "default_visible": True,
                "default_order": 10,
                "active_endpoints": ["pending.pending_page"],
            },
            {
                "page_id": "recurring_rules",
                "endpoint": "pending.recurring_page",
                "label_key": "nav.recurring_rules",
                "section_label_key": "nav.scheduled_money",
                "default_visible": True,
                "default_order": 20,
                "active_endpoints": ["pending.recurring_page"],
            },
            {
                "page_id": "expense_projects",
                "endpoint": "expense_projects.expense_projects_page",
                "label_key": "nav.expense_projects",
                "section_label_key": "nav.projects_forecast",
                "default_visible": True,
                "default_order": 30,
                "active_endpoints": [
                    "expense_projects.expense_projects_page",
                    "expense_projects.expense_project_detail",
                ],
            },
            {
                "page_id": "forecast",
                "endpoint": "forecast.forecast",
                "label_key": "nav.forecast",
                "section_label_key": "nav.projects_forecast",
                "default_visible": True,
                "default_order": 40,
                "active_endpoints": ["forecast.forecast"],
            },
            {
                "page_id": "payables",
                "endpoint": "payables.payables_page",
                "label_key": "nav.payables",
                "section_label_key": "nav.obligations",
                "default_visible": True,
                "default_order": 50,
                "active_endpoints": ["payables.payables_page"],
            },
            {
                "page_id": "debts",
                "endpoint": "debts.debts_page",
                "label_key": "nav.debts_i_owe",
                "section_label_key": "nav.obligations",
                "default_visible": True,
                "default_order": 60,
                "active_endpoints": ["debts.debts_page"],
            },
            {
                "page_id": "receivables",
                "endpoint": "receivables.receivables_page",
                "label_key": "nav.money_owed_to_me",
                "section_label_key": "nav.obligations",
                "default_visible": True,
                "default_order": 70,
                "active_endpoints": ["receivables.receivables_page"],
            },
        ],
    },
    {
        "group_id": "accounts",
        "label_key": "nav.accounts",
        "default_open": True,
        "default_order": 20,
        "items": [
            {
                "page_id": "accounts",
                "endpoint": "accounts.accounts_page",
                "label_key": "nav.liquid_accounts",
                "default_visible": True,
                "default_order": 10,
                "active_endpoints": ["accounts.accounts_page", "accounts.account_detail"],
            },
            {
                "page_id": "contacts",
                "endpoint": "contacts.contacts_page",
                "label_key": "nav.contacts",
                "default_visible": True,
                "default_order": 40,
                "active_endpoints": [
                    "contacts.contacts_page",
                    "contacts.new_contact",
                    "contacts.contact_detail",
                    "contacts.edit_contact",
                ],
            },
            {
                "page_id": "bonifico",
                "endpoint": "bonifico.bonifico_page",
                "label_key": "nav.bonifico",
                "default_visible": True,
                "default_order": 30,
                "active_endpoints": ["bonifico.bonifico_page", "bonifico.contacts_search_api"],
            },
            {
                "page_id": "internal_transfers",
                "endpoint": "internal_transfers.internal_transfers_page",
                "label_key": "nav.internal_transfers",
                "default_visible": True,
                "default_order": 20,
                "active_endpoints": ["internal_transfers.internal_transfers_page"],
            },
            {
                "page_id": "currencies",
                "endpoint": "currencies.currencies_page",
                "label_key": "nav.currency_exchange",
                "default_visible": True,
                "default_order": 50,
                "active_endpoints": ["currencies.currencies_page"],
            },
            {
                "page_id": "documents",
                "endpoint": "documents.documents",
                "label_key": "nav.documents",
                "default_visible": True,
                "default_order": 60,
                "active_endpoints": ["documents.documents"],
            },
            {
                "page_id": "sparagnat",
                "endpoint": "sparagnat.sparagnat_page",
                "label_key": "nav.sparagnat",
                "default_visible": True,
                "default_order": 70,
                "active_endpoints": ["sparagnat.sparagnat_page"],
            },
            {
                "page_id": "parent_support",
                "endpoint": "parent_support.parent_support_page",
                "label_key": "nav.parent_support",
                "default_visible": True,
                "default_order": 80,
                "active_endpoints": ["parent_support.parent_support_page"],
            },
        ],
    },
    {
        "group_id": "analysis_wealth",
        "label_key": "nav.analysis_wealth",
        "default_open": False,
        "default_order": 40,
        "items": [
            {
                "page_id": "analysis",
                "endpoint": "analysis.analysis",
                "label_key": "nav.analysis",
                "default_visible": True,
                "default_order": 10,
                "active_endpoints": ["analysis.analysis"],
            },
            {
                "page_id": "investments",
                "endpoint": "investments.investments_page",
                "label_key": "nav.investments",
                "default_visible": True,
                "default_order": 20,
                "active_endpoints": ["investments.investments_page"],
            },
            {
                "page_id": "yearly_summary",
                "endpoint": "yearly_summary.yearly_summary_page",
                "label_key": "nav.yearly_summary",
                "default_visible": True,
                "default_order": 30,
                "active_endpoints": ["yearly_summary.yearly_summary_page"],
            },
        ],
    },
    {
        "group_id": "settings",
        "label_key": "nav.settings",
        "default_open": False,
        "default_order": 90,
        "items": [
            {
                "page_id": "integrity",
                "endpoint": "integrity.integrity_page",
                "label_key": "nav.integrity",
                "default_visible": True,
                "default_order": 10,
                "active_endpoints": ["integrity.integrity_page"],
            },
            {
                "page_id": "security",
                "endpoint": "security.security_page",
                "label_key": "nav.security",
                "default_visible": True,
                "default_order": 20,
                "active_endpoints": ["security.security_page", "security.unlock"],
            },
            {
                "page_id": "updates",
                "endpoint": "settings_updates.updates_page",
                "label_key": "nav.updates",
                "default_visible": True,
                "default_order": 30,
                "active_endpoints": ["settings_updates.updates_page", "settings_updates.stage_update_route", "settings_updates.rollback_route"],
            },
            {
                "page_id": "data_registry",
                "endpoint": "settings_updates.data_registry_page",
                "label_key": "nav.data_registry",
                "default_visible": True,
                "default_order": 40,
                "active_endpoints": ["settings_updates.data_registry_page"],
            },
            {
                "page_id": "cache",
                "endpoint": "settings_cache.cache_page",
                "label_key": "nav.cache",
                "default_visible": True,
                "default_order": 50,
                "active_endpoints": ["settings_cache.cache_page", "settings_cache.clear_cache_route", "settings_cache.rebuild_cache_route", "settings_cache.cleanup_stale_route"],
            },
            {
                "page_id": "categories",
                "endpoint": "settings_categories.categories_page",
                "label_key": "nav.categories",
                "default_visible": True,
                "default_order": 60,
                "active_endpoints": [
                    "settings_categories.categories_page",
                    "settings_categories.add_category_route",
                    "settings_categories.hide_category_route",
                    "settings_categories.restore_category_route",
                    "settings_categories.default_category_route",
                ],
            },
        ],
    },

]


def navigation_registry() -> list[dict[str, Any]]:
    """Return a mutable copy of the app navigation registry."""
    return deepcopy(DEFAULT_NAVIGATION)


def registry_page_ids() -> set[str]:
    return {item["page_id"] for group in DEFAULT_NAVIGATION for item in group.get("items", [])}


def registry_group_ids() -> set[str]:
    return {group["group_id"] for group in DEFAULT_NAVIGATION}
