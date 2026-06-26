from datetime import date
import calendar

from money_manager.config import RECURRING_CSV
from money_manager.domain.constants import RECURRING_FIELDS
from money_manager.repositories.csv_files import next_numeric_id, read_rows, write_rows


def load_recurring() -> list[dict]:
    return [_normalize_row(row) for row in read_rows(RECURRING_CSV, RECURRING_FIELDS)]


def write_recurring(rows: list[dict]) -> None:
    write_rows(RECURRING_CSV, RECURRING_FIELDS, [_normalize_row(row) for row in rows])


def append_recurring(rule: dict) -> int | None:
    rows = load_recurring()
    row = {
        "id": str(next_numeric_id(rows)),
        "name": rule.get("name", ""),
        "type": rule.get("type", "expense"),
        "amount": str(rule.get("amount", 0.0)),
        "frequency": str(parse_frequency_months(rule.get("frequency", 1))),
        "day_of_month": str(rule.get("day_of_month", 1)),
        "category": rule.get("category", ""),
        "account": rule.get("account", "auto"),
        "account_id": rule.get("account_id", ""),
        "account_name_snapshot": rule.get("account_name_snapshot", ""),
        "payment_method_id": rule.get("payment_method_id", ""),
        "payment_method_name_snapshot": rule.get("payment_method_name_snapshot", ""),
        "payment_resolution_template_json": rule.get("payment_resolution_template_json", ""),
        "start_date": (parse_date(rule.get("start_date")) or date.today()).isoformat(),
        "end_date": _clean_date_field(rule.get("end_date", "")),
        "max_occurrences": _clean_max_occurrences(rule.get("max_occurrences", "")),
        "last_generated": "",
    }
    rows.append(row)
    write_recurring(rows)
    try:
        return int(row["id"])
    except (TypeError, ValueError):
        return None


def update_recurring(rule_id, updates: dict) -> None:
    """Update a rule without rewriting history.

    Past generated/executed pending rows are not edited.  Open pending rows are
    handled by the service before this function is called, and future generated
    rows will use the updated values.
    """
    rows = load_recurring()

    for row in rows:
        if str(row.get("id", "")) != str(rule_id):
            continue

        row["name"] = updates.get("name", row.get("name", ""))
        row["type"] = updates.get("type", row.get("type", "expense"))
        row["amount"] = str(updates.get("amount", row.get("amount", "0")))
        row["frequency"] = str(parse_frequency_months(updates.get("frequency", row.get("frequency", 1))))
        row["day_of_month"] = str(updates.get("day_of_month", row.get("day_of_month", 1)))
        row["category"] = updates.get("category", row.get("category", ""))
        row["account"] = updates.get("account", row.get("account", "auto"))
        for key in ["account_id", "account_name_snapshot", "payment_method_id", "payment_method_name_snapshot", "payment_resolution_template_json"]:
            if key in updates:
                row[key] = updates.get(key, "")
        row["start_date"] = updates.get("start_date") or row.get("start_date") or date.today().isoformat()
        row["end_date"] = _clean_date_field(updates.get("end_date", row.get("end_date", "")))
        row["max_occurrences"] = _clean_max_occurrences(
            updates.get("max_occurrences", row.get("max_occurrences", ""))
        )
        if "last_generated" in updates:
            row["last_generated"] = _clean_date_field(updates.get("last_generated", ""))
        # Otherwise intentionally keep last_generated. Resetting it can
        # regenerate old periods with the new amount after a price/schedule edit.
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


def parse_max_occurrences(value) -> int | None:
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    try:
        occurrences = int(float(text))
    except (TypeError, ValueError):
        return None

    return occurrences if occurrences > 0 else None


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


def occurrence_count_until(row: dict, until_date: date | None) -> int:
    """Count scheduled occurrences from the first due date up to until_date."""
    if until_date is None:
        return 0

    frequency_months = parse_frequency_months(row.get("frequency"))
    try:
        desired_day = int(row.get("day_of_month", 1))
    except (TypeError, ValueError):
        desired_day = 1

    start = first_due_date(row, until_date)
    count = 0
    current = start

    # Safety cap avoids infinite loops if corrupted data sneaks in.
    for _ in range(2400):
        if current > until_date:
            break
        count += 1
        current = add_months(current, frequency_months, desired_day)

    return count


def normalize_amount(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _clean_date_field(value) -> str:
    parsed = parse_date(value)
    return parsed.isoformat() if parsed else ""


def _clean_max_occurrences(value) -> str:
    parsed = parse_max_occurrences(value)
    return str(parsed) if parsed else ""


def _normalize_row(row: dict) -> dict:
    normalized = {field: row.get(field, "") for field in RECURRING_FIELDS}
    normalized["frequency"] = str(parse_frequency_months(normalized.get("frequency")))
    normalized["max_occurrences"] = _clean_max_occurrences(normalized.get("max_occurrences", ""))
    normalized["end_date"] = _clean_date_field(normalized.get("end_date", ""))

    # The UI treats the two stopping options as alternatives:
    # either stop on an exact date OR stop after N occurrences.
    # If both values exist because of an old edit, keep the occurrence limit
    # and ignore the date cap, otherwise quarterly rules can be stopped too soon.
    if normalized["max_occurrences"]:
        normalized["end_date"] = ""

    return normalized
