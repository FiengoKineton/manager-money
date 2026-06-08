"""Editable transaction categories and default selections.

This is intentionally the single file to change when you want to add, remove,
rename, or reorder categories. The UI default is controlled explicitly by
DEFAULT_CATEGORY_BY_TYPE, so it no longer depends on alphabetical order.
"""

TRANSACTION_TYPES = ["expense", "income", "investment"]

CATEGORY_OPTIONS = {
    "expense": sorted([
        "Rent",
        "Groceries",
        "Restaurants",
        "Eating out",
        "Eating in",
        "Going out",
        "Pre-paid card",
        "Claudia",
        "Family",
        "Shopping",
        "Transportation",
        "Health",
        "Personal care",
        "Credit cards",
        "Subscriptions",
        "Utilities",
        "Gifts",
        "Charity",
        "Travel",
        "Savings",
        "Other",
        "Lost",
        "Coffe",
        "Housing",
        "Debt",
    ]),
    "income": sorted([
        "PoliMi",
        "Kineton",
        "Deddo",
        "Salary",
        "Scholarship",
        "Other income",
        "Refund",
        "Gift",
        "Cash",
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
    "expense": "Other",
    "income": "Kineton",
    "investment": "Deposit",
}


def categories_for(transaction_type: str) -> list[str]:
    return CATEGORY_OPTIONS.get(transaction_type, [])


def default_category_for(transaction_type: str) -> str:
    categories = categories_for(transaction_type)
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
