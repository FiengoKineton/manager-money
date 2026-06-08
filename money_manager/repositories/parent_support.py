from datetime import datetime

from money_manager.config import PARENT_SUPPORT_CSV, PARENT_SUPPORT_RULES_CSV
from money_manager.domain.constants import (
    PARENT_SUPPORT_FIELDS,
    PARENT_SUPPORT_RULE_FIELDS,
)
from money_manager.repositories.csv_files import (
    append_row,
    next_numeric_id,
    read_rows,
    write_rows,
)


def load_entries() -> list[dict]:
    return read_rows(PARENT_SUPPORT_CSV, PARENT_SUPPORT_FIELDS)


def append_entry(entry: dict) -> None:
    rows = load_entries()
    row = {
        "id": next_numeric_id(rows),
        "date": entry.get("date", ""),
        "kind": entry.get("kind", "direct_money"),
        "parent": entry.get("parent", ""),
        "category": entry.get("category", ""),
        "amount": entry.get("amount", 0.0),
        "payment_method": entry.get("payment_method", ""),
        "description": entry.get("description", ""),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    append_row(PARENT_SUPPORT_CSV, PARENT_SUPPORT_FIELDS, row)


def delete_entry(entry_id: int) -> None:
    rows = [row for row in load_entries() if str(row.get("id", "")) != str(entry_id)]
    write_rows(PARENT_SUPPORT_CSV, PARENT_SUPPORT_FIELDS, rows)


def load_rules() -> list[dict]:
    return read_rows(PARENT_SUPPORT_RULES_CSV, PARENT_SUPPORT_RULE_FIELDS)


def append_rule(rule: dict) -> None:
    rows = load_rules()
    row = {
        "id": next_numeric_id(rows),
        "name": rule.get("name", ""),
        "kind": rule.get("kind", "covered_expense"),
        "parent": rule.get("parent", ""),
        "category": rule.get("category", ""),
        "monthly_amount": rule.get("monthly_amount", 0.0),
        "day_of_month": rule.get("day_of_month", 1),
        "start_date": rule.get("start_date", ""),
        "end_date": rule.get("end_date", ""),
        "payment_method": rule.get("payment_method", ""),
        "description": rule.get("description", ""),
        "active": rule.get("active", "yes"),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    append_row(PARENT_SUPPORT_RULES_CSV, PARENT_SUPPORT_RULE_FIELDS, row)


def delete_rule(rule_id: int) -> None:
    rows = [row for row in load_rules() if str(row.get("id", "")) != str(rule_id)]
    write_rows(PARENT_SUPPORT_RULES_CSV, PARENT_SUPPORT_RULE_FIELDS, rows)