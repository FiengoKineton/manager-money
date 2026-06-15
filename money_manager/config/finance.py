from datetime import date

# This is kept only for backward compatibility if another file imports it.
# The real default period is dynamic and starts from January 1st of the current year.
DEFAULT_DATE_RANGE_START = None
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
    "paypal_credit",
    "paypal credit",
    "pay pal credit",
    "paypal card",
    "pay pal card",
    "paypal",
    "pay pal",
}


def default_date_range(today: date | None = None) -> tuple[str, str]:
    """Default display range: January 1st of the current year through today.

    This is used for pages that show logs, tables, charts, and filter forms.
    Balance calculations should use the full transaction history instead of this
    display range, so old opening rows in the CSV still count.
    """
    current = today or date.today()
    return date(current.year, 1, 1).isoformat(), current.isoformat()
