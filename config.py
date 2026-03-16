# config.py
from pathlib import Path
from datetime import date

BASE_DIR = Path(__file__).resolve().parent

DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True, parents=True)

EXPENSES_CSV = DATA_DIR / "expenses.csv"
INCOMES_CSV = DATA_DIR / "incomes.csv"
INVESTMENTS_CSV = DATA_DIR / "investments.csv"

PLOTS_DIR = BASE_DIR / "static" / "plots"
PLOTS_DIR.mkdir(exist_ok=True, parents=True)

EXPENSE_CATEGORIES = sorted([
    "Rent",
    "Groceries",
    "Restaurants",
    "Eating out",
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
])


INCOME_CATEGORIES = sorted([
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
])


INVESTMENT_CATEGORIES = sorted([
    "Deposit",
    "Withdrawal",
    "Buy",
    "Sell",
    "Dividend",
    "Other",
])

DEFAULT_TYPES = ["expense", "income", "investment"]

def default_date_range():
    """Return (start_date, end_date) for current year as ISO strings."""
    today = date.today()
    #start = date(today.year, 1, 1)
    start = date(2025, 9, 7)
    end = today # date(today.year, 12, 31)
    return start.isoformat(), end.isoformat()
