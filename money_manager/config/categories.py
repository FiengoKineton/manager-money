"""Generic transaction categories.

User-specific categories are not defined here.  Effective categories are:

    generic defaults + data/users/{user_id}/categories.json custom - hidden

See money_manager.services.custom_category_service for the per-user layer.
"""

TRANSACTION_TYPES = ["expense", "income", "investment"]

CATEGORY_OPTIONS = {
    "expense": sorted([
        "Food",
        "Groceries",
        "Restaurants",
        "Transport",
        "Housing",
        "Utilities",
        "Health",
        "Personal care",
        "Shopping",
        "Subscriptions",
        "Travel",
        "Gifts",
        "Charity",
        "Savings",
        "Debt",
        "Credit cards",
        "Payable",
        "Account cleanup",
        "Other",
    ]),
    "income": sorted([
        "Salary",
        "Scholarship",
        "Refund",
        "Gift",
        "Family",
        "Friends",
        "Other income",
        "Other",
    ]),
    "investment": sorted([
        "Deposit",
        "Withdrawal",
        "Buy",
        "Sell",
        "Dividend",
        "Other",
    ]),
}

DEFAULT_CATEGORY_BY_TYPE = {
    "expense": "Food",
    "income": "Other",
    "investment": "Deposit",
}


def categories_for(transaction_type: str) -> list[str]:
    try:
        from money_manager.services.custom_category_service import effective_categories_for

        return effective_categories_for(transaction_type)
    except Exception:
        return CATEGORY_OPTIONS.get(transaction_type, [])


def default_category_for(transaction_type: str) -> str:
    try:
        from money_manager.services.custom_category_service import default_category_for as user_default_category_for

        return user_default_category_for(transaction_type)
    except Exception:
        categories = CATEGORY_OPTIONS.get(transaction_type, [])
        configured_default = DEFAULT_CATEGORY_BY_TYPE.get(transaction_type, "")
        if configured_default in categories:
            return configured_default
        return categories[0] if categories else ""


PARENT_SUPPORT_KINDS = {
    "direct_money": "Money given to me",
    "covered_expense": "Expense covered for me",
}

PARENT_SUPPORT_CATEGORIES = sorted([
    "Fuel",
    "House rent",
    "House mortgage",
    "Groceries",
    "Bills",
    "Car",
    "University",
    "Health",
    "Phone",
    "Cash",
    "Other",
])

DEFAULT_PARENT_SUPPORT_CATEGORY = "Fuel"
