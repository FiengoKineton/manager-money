from datetime import date
import calendar

from money_manager.config import RECURRING_CSV
from money_manager.domain.constants import RECURRING_FIELDS
from money_manager.repositories.csv_files import next_numeric_id, read_rows, write_rows


def load_recurring() -> list[dict]:
    return [_normalize_row(row) for row in read_rows(RECURRING_CSV, RECURRING_FIELDS)]


def write_recurring(rows: list[dict]) -> None:
    write_rows(RECURRING_CSV, RECURRING_FIELDS, [_normalize_row(row) for row in rows])


def append_recurring(rule: dict) -> None:
    rows = load_recurring()
    row = {
        "id": str(next_numeric_id(rows)),
        "name": rule.get("name", ""),
        "type": rule.get("type", "expense"),
        "amount": str(rule.get("amount", 0.0)),
        "frequency": str(parse_frequency_months(rule.get("frequency", 1))),
        "day_of_month": str(rule.get("day_of_month", 1)),
        "category": rule.get("category", ""),
        "start_date": (parse_date(rule.get("start_date")) or date.today()).isoformat(),
        "last_generated": "",
    }
    rows.append(row)
    write_recurring(rows)


def update_recurring(rule_id, updates: dict) -> None:
    rows = load_recurring()
    today = date.today().isoformat()

    for row in rows:
        if str(row.get("id", "")) != str(rule_id):
            continue

        row["name"] = updates.get("name", row.get("name", ""))
        row["type"] = updates.get("type", row.get("type", "expense"))
        row["amount"] = str(updates.get("amount", row.get("amount", "0")))
        row["frequency"] = str(parse_frequency_months(updates.get("frequency", row.get("frequency", 1))))
        row["day_of_month"] = str(updates.get("day_of_month", row.get("day_of_month", 1)))
        row["category"] = updates.get("category", row.get("category", ""))
        row["start_date"] = today
        row["last_generated"] = ""
        break

    write_recurring(rows)


def delete_recurring(rule_id) -> None:
    rows = [row for row in load_recurring() if str(row.get("id", "")) != str(rule_id)]
    write_recurring(rows)


def parse_frequency_months(value) -> int:
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


def parse_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def valid_day_for_month(year: int, month: int, desired_day: int) -> int:
    last_day = calendar.monthrange(year, month)[1]
    desired_day = max(1, min(int(desired_day), 31))
    return min(desired_day, last_day)


def add_months(due_date: date, months: int, desired_day: int) -> date:
    month_index = due_date.year * 12 + (due_date.month - 1) + months
    year = month_index // 12
    month = month_index % 12 + 1
    day = valid_day_for_month(year, month, desired_day)
    return date(year, month, day)


def first_due_date(row: dict, today: date) -> date:
    start_date = parse_date(row.get("start_date")) or today

    try:
        desired_day = int(row.get("day_of_month", 1))
    except (TypeError, ValueError):
        desired_day = 1

    valid_day = valid_day_for_month(start_date.year, start_date.month, desired_day)
    due_date = date(start_date.year, start_date.month, valid_day)

    if due_date < start_date:
        due_date = add_months(due_date, 1, desired_day)

    return due_date


def normalize_amount(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _normalize_row(row: dict) -> dict:
    normalized = {field: row.get(field, "") for field in RECURRING_FIELDS}
    normalized["frequency"] = str(parse_frequency_months(normalized.get("frequency")))
    return normalized
