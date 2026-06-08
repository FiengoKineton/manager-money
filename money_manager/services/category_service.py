from money_manager.config import (
    CATEGORY_OPTIONS,
    DEFAULT_CATEGORY_BY_TYPE,
    TRANSACTION_TYPES,
    account_options_for_forms,
    categories_for,
    default_category_for,
)


def category_context(transaction_type: str) -> dict:
    if transaction_type not in TRANSACTION_TYPES:
        transaction_type = "expense"

    return {
        "ttype": transaction_type,
        "categories": categories_for(transaction_type),
        "default_category": default_category_for(transaction_type),
        "account_options": account_options_for_forms(),
    }


def category_payload() -> dict:
    return {
        "categories_by_type": CATEGORY_OPTIONS,
        "default_category_by_type": DEFAULT_CATEGORY_BY_TYPE,
    }
