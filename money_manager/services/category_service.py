from money_manager.config import TRANSACTION_TYPES, account_options_for_forms
from money_manager.services.custom_category_service import (
    default_category_for,
    effective_categories_by_type,
    effective_categories_for,
)


def category_context(transaction_type: str) -> dict:
    if transaction_type not in TRANSACTION_TYPES:
        transaction_type = "expense"

    return {
        "ttype": transaction_type,
        "categories": effective_categories_for(transaction_type),
        "default_category": default_category_for(transaction_type),
        "account_options": account_options_for_forms(),
    }


def category_payload() -> dict:
    categories_by_type = effective_categories_by_type()
    return {
        "categories_by_type": categories_by_type,
        "default_category_by_type": {
            transaction_type: default_category_for(transaction_type)
            for transaction_type in TRANSACTION_TYPES
        },
    }
