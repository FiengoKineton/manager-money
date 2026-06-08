from datetime import date

DEFAULT_DATE_RANGE_START = date(2025, 9, 7)
CREDIT_CARD_DUE_DAY = 15
CREDIT_CARD_PAYMENT_CATEGORY = "Credit cards"
DEBT_PAYMENT_CATEGORY = "Debt"

CREDIT_ACCOUNT_KEYWORDS = {
    "credit",
    "credit card",
    "card credit",
    "carta credito",
    "carta di credito",
    "visa",
    "mastercard",
}


def default_date_range() -> tuple[str, str]:
    """Default dashboard date range as ISO strings."""
    return DEFAULT_DATE_RANGE_START.isoformat(), date.today().isoformat()
