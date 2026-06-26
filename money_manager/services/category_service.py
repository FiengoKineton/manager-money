from money_manager.config import TRANSACTION_TYPES, account_options_for_forms
from money_manager.services.custom_category_service import (
    default_category_for,
    effective_categories_by_type,
    effective_categories_for,
)
from money_manager.services.category_icon_service import (
    category_option_rows,
    icons_for_categories_by_type,
)


def category_context(transaction_type: str) -> dict:
    if transaction_type not in TRANSACTION_TYPES:
        transaction_type = "expense"

    categories = effective_categories_for(transaction_type)
    return {
        "ttype": transaction_type,
        "categories": categories,
        "category_rows": category_option_rows(transaction_type, categories),
        "default_category": default_category_for(transaction_type),
        "account_options": account_options_for_forms(),
    }


def category_payload() -> dict:
    categories_by_type = effective_categories_by_type()
    return {
        "categories_by_type": categories_by_type,
        "category_icons_by_type": icons_for_categories_by_type(categories_by_type),
        "default_category_by_type": {
            transaction_type: default_category_for(transaction_type)
            for transaction_type in TRANSACTION_TYPES
        },
    }
