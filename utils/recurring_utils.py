from datetime import date
import csv
import calendar
from config import DATA_DIR
from utils.pending_utils import append_pending, load_pending

RECURRING_CSV = DATA_DIR / "recurring.csv"

RECURRING_FIELDS = [
    "id",
    "name",
    "type",
    "amount",
    "frequency",
    "day_of_month",
    "category",
    "start_date",
    "last_generated",
]


def _ensure_recurring_csv():
    """Create recurring.csv with the correct header if it does not exist."""
    if not RECURRING_CSV.exists():
        with RECURRING_CSV.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=RECURRING_FIELDS)
            writer.writeheader()


def _parse_frequency_months(value):
    """
    Convert the recurring frequency to an integer number of months.

    Backward compatibility:
    - old rows stored "monthly" -> 1
    - common labels like "quarterly"/"yearly" are accepted
    - invalid or missing values fall back to monthly
    """
    if value is None:
        return 1

    text = str(value).strip().lower()
    if not text:
        return 1

    aliases = {
        "monthly": 1,
        "month": 1,
        "every month": 1,
        "quarterly": 3,
        "quarter": 3,
        "yearly": 12,
        "annual": 12,
        "annually": 12,
        "year": 12,
    }
    if text in aliases:
        return aliases[text]

    try:
        months = int(float(text))
    except (TypeError, ValueError):
        return 1

    return max(1, months)


def _normalize_row(row):
    """
    Keep the recurring CSV schema stable even if older rows miss columns.
    Frequency is stored as an integer number of months, as text in the CSV.
    """
    normalized = {field: row.get(field, "") for field in RECURRING_FIELDS}
    normalized["frequency"] = str(_parse_frequency_months(normalized.get("frequency")))
    return normalized


def _write_recurring(rows):
    _ensure_recurring_csv()
    with RECURRING_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=RECURRING_FIELDS)
        writer.writeheader()
        writer.writerows([_normalize_row(r) for r in rows])


def _parse_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def get_valid_date(year, month, desired_day):
    """Return the real calendar day for this month, clamping 29/30/31 safely."""
    last_day = calendar.monthrange(year, month)[1]
    desired_day = max(1, min(int(desired_day), 31))
    return min(desired_day, last_day)


def _add_months(due_date, months, desired_day):
    """Move a due date forward by N months while respecting month length."""
    month_index = due_date.year * 12 + (due_date.month - 1) + months
    year = month_index // 12
    month = month_index % 12 + 1
    day = get_valid_date(year, month, desired_day)
    return date(year, month, day)


def _first_due_date(row, today):
    """
    Return the first due date on or after the rule start date.

    Example:
    - created on 2026-05-08, day 10 -> first due 2026-05-10
    - created on 2026-05-12, day 10 -> first due 2026-06-10
    """
    start_date = _parse_date(row.get("start_date")) or today

    try:
        desired_day = int(row.get("day_of_month", 1))
    except (TypeError, ValueError):
        desired_day = 1

    valid_day = get_valid_date(start_date.year, start_date.month, desired_day)
    due_date = date(start_date.year, start_date.month, valid_day)

    if due_date < start_date:
        due_date = _add_months(due_date, 1, desired_day)

    return due_date


def load_recurring():
    _ensure_recurring_csv()
    with RECURRING_CSV.open(newline="", encoding="utf-8") as f:
        return [_normalize_row(row) for row in csv.DictReader(f)]


def _matching_pending_exists(row, due_date):
    """
    Safety net for rows created before last_generated existed/was updated.
    If a matching pending/executed item already exists for this same due date,
    do not create another one.
    """
    due = due_date.isoformat()
    name = str(row.get("name", ""))
    r_type = str(row.get("type", ""))
    category = str(row.get("category", ""))

    try:
        amount = float(row.get("amount", 0))
    except (TypeError, ValueError):
        amount = 0.0

    for tx in load_pending():
        if tx.get("date_due") != due:
            continue
        if tx.get("description") != name:
            continue
        if tx.get("type") != r_type:
            continue
        if tx.get("category") != category:
            continue

        try:
            tx_amount = float(tx.get("amount", 0))
        except (TypeError, ValueError):
            tx_amount = 0.0

        if abs(tx_amount - amount) < 0.01:
            return True

    return False


def _iter_due_dates_to_generate(row, today):
    """
    Yield due dates that should exist for this recurring rule but have not yet
    been generated according to last_generated.
    """
    frequency_months = _parse_frequency_months(row.get("frequency"))

    try:
        desired_day = int(row.get("day_of_month", 1))
    except (TypeError, ValueError):
        desired_day = 1

    due_date = _first_due_date(row, today)
    last_generated = _parse_date(row.get("last_generated"))

    # Skip all recurrence dates that have already been processed.
    if last_generated:
        while due_date <= last_generated:
            due_date = _add_months(due_date, frequency_months, desired_day)

    # Create all missing due dates up to today. For normal use this is usually
    # just one row, but it also catches up safely if you did not open the app
    # for a few months.
    while due_date <= today:
        yield due_date
        due_date = _add_months(due_date, frequency_months, desired_day)


def generate_recurring(today=None):
    """
    Generate due recurring payments according to their frequency in months.

    Important behavior:
    - frequency = 1 means monthly, 2 means every two months, etc.
    - Uses last_generated to remember the latest generated due date.
    - Uses start_date to decide the first valid due date.
    - Keeps old "monthly" rows working by treating them as frequency 1.
    - Avoids duplicate pending rows for the same recurring rule and due date.
    - Returns the number of new pending rows created.
    """
    today = today or date.today()
    rows = load_recurring()

    changed = False
    created = 0

    for row in rows:
        for due_date in _iter_due_dates_to_generate(row, today):
            # Extra protection for older data where last_generated may still be blank.
            if _matching_pending_exists(row, due_date):
                row["last_generated"] = due_date.isoformat()
                changed = True
                continue

            append_pending(
                {
                    "type": row["type"],
                    "amount": float(row["amount"]),
                    "category": row["category"],
                    "account": "auto",
                    "description": row["name"],
                },
                due_date,
            )

            row["last_generated"] = due_date.isoformat()
            changed = True
            created += 1

    if changed:
        _write_recurring(rows)

    return created

def next_due_date_for_rule(row, today=None):
    """
    Return the next scheduled payment date for a recurring rule.

    This is the next date after last_generated if the rule has already produced
    a payment. Otherwise, it is the first due date from the rule start date.
    """
    today = today or date.today()

    frequency_months = _parse_frequency_months(row.get("frequency"))

    try:
        desired_day = int(row.get("day_of_month", 1))
    except (TypeError, ValueError):
        desired_day = 1

    last_generated = _parse_date(row.get("last_generated"))

    if last_generated:
        return _add_months(last_generated, frequency_months, desired_day)

    return _first_due_date(row, today)

def append_recurring(rule):
    rows = load_recurring()
    new_id = max([int(r["id"]) for r in rows if str(r.get("id", "")).isdigit()], default=0) + 1

    row = {
        "id": str(new_id),
        "name": rule["name"],
        "type": rule["type"],
        "amount": str(rule["amount"]),
        "frequency": str(_parse_frequency_months(rule.get("frequency", 1))),
        "day_of_month": str(rule["day_of_month"]),
        "category": rule["category"],
        "start_date": (_parse_date(rule.get("start_date")) or date.today()).isoformat(),
        "last_generated": "",
    }

    rows.append(row)
    _write_recurring(rows)

def update_recurring(rule_id, updates):
    """
    Update a recurring rule from today onward.

    Past generated pending/executed payments are not modified because they are
    already stored separately in pending.csv / expenses.csv.
    """
    rows = load_recurring()
    today = date.today().isoformat()

    for row in rows:
        if str(row.get("id", "")) == str(rule_id):
            row["name"] = updates.get("name", row.get("name", ""))
            row["type"] = updates.get("type", row.get("type", "expense"))
            row["amount"] = str(updates.get("amount", row.get("amount", "0")))
            row["frequency"] = str(_parse_frequency_months(updates.get("frequency", row.get("frequency", 1))))
            row["day_of_month"] = str(updates.get("day_of_month", row.get("day_of_month", 1)))
            row["category"] = updates.get("category", row.get("category", ""))

            # From the moment of modification onward
            row["start_date"] = today
            row["last_generated"] = ""

            break

    _write_recurring(rows)

def delete_recurring(rule_id):
    rows = load_recurring()
    rows = [r for r in rows if str(r.get("id", "")) != str(rule_id)]
    _write_recurring(rows)
