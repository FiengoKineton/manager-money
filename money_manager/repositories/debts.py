from datetime import datetime

from money_manager.config import DEBTS_CSV, DEBT_RULES_CSV
from money_manager.domain.constants import DEBT_FIELDS, DEBT_RULE_FIELDS
from money_manager.repositories.csv_files import append_row, next_numeric_id, read_rows, write_rows


def load_debts() -> list[dict]:
    return [_normalize_debt(row) for row in read_rows(DEBTS_CSV, DEBT_FIELDS)]


def write_debts(rows: list[dict]) -> None:
    write_rows(DEBTS_CSV, DEBT_FIELDS, [_normalize_debt(row) for row in rows])


def append_debt(data: dict) -> None:
    rows = load_debts()
    amount = _amount(data.get("original_amount"))
    row = {
        "id": next_numeric_id(rows),
        "name": data.get("name", ""),
        "creditor": data.get("creditor", ""),
        "original_amount": amount,
        "remaining_amount": _amount(data.get("remaining_amount", amount)),
        "category": data.get("category", "Debt"),
        "account": data.get("account", ""),
        "start_date": data.get("start_date", ""),
        "due_date": data.get("due_date", ""),
        "description": data.get("description", ""),
        "status": data.get("status", "active"),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "closed_at": "",
    }
    append_row(DEBTS_CSV, DEBT_FIELDS, row)


def update_debt(debt_id: int, updates: dict) -> None:
    rows = load_debts()
    for row in rows:
        if str(row.get("id")) != str(debt_id):
            continue
        for key in ["name", "creditor", "category", "account", "start_date", "due_date", "description", "status", "closed_at"]:
            if key in updates:
                row[key] = updates[key]
        for key in ["original_amount", "remaining_amount"]:
            if key in updates:
                row[key] = _amount(updates[key])
        break
    write_debts(rows)


def delete_debt(debt_id: int) -> None:
    rows = [row for row in load_debts() if str(row.get("id")) != str(debt_id)]
    write_debts(rows)


def load_debt_rules() -> list[dict]:
    return [_normalize_rule(row) for row in read_rows(DEBT_RULES_CSV, DEBT_RULE_FIELDS)]


def write_debt_rules(rows: list[dict]) -> None:
    write_rows(DEBT_RULES_CSV, DEBT_RULE_FIELDS, [_normalize_rule(row) for row in rows])


def append_debt_rule(data: dict) -> None:
    rows = load_debt_rules()
    row = {
        "id": next_numeric_id(rows),
        "debt_id": data.get("debt_id", ""),
        "name": data.get("name", ""),
        "amount": _amount(data.get("amount")),
        "frequency": max(1, int(float(data.get("frequency", 1) or 1))),
        "day_of_month": max(1, min(31, int(float(data.get("day_of_month", 1) or 1)))),
        "start_date": data.get("start_date", ""),
        "last_generated": "",
        "active": "1",
    }
    append_row(DEBT_RULES_CSV, DEBT_RULE_FIELDS, row)


def delete_debt_rule(rule_id: int) -> None:
    rows = [row for row in load_debt_rules() if str(row.get("id")) != str(rule_id)]
    write_debt_rules(rows)


def update_debt_rule(rule_id: int, updates: dict) -> None:
    rows = load_debt_rules()
    for row in rows:
        if str(row.get("id")) != str(rule_id):
            continue
        for key, value in updates.items():
            if key == "amount":
                row[key] = _amount(value)
            elif key in {"frequency", "day_of_month"}:
                row[key] = str(max(1, int(float(value or 1))))
            else:
                row[key] = value
        break
    write_debt_rules(rows)


def _amount(value) -> float:
    try:
        return max(0.0, float(str(value).replace(",", ".")))
    except (TypeError, ValueError):
        return 0.0


def _normalize_debt(row: dict) -> dict:
    normalized = {field: row.get(field, "") for field in DEBT_FIELDS}
    normalized["original_amount"] = _amount(normalized.get("original_amount"))
    normalized["remaining_amount"] = _amount(normalized.get("remaining_amount"))
    if not normalized["status"]:
        normalized["status"] = "active" if normalized["remaining_amount"] > 0 else "paid"
    return normalized


def _normalize_rule(row: dict) -> dict:
    normalized = {field: row.get(field, "") for field in DEBT_RULE_FIELDS}
    normalized["amount"] = _amount(normalized.get("amount"))
    try:
        normalized["frequency"] = str(max(1, int(float(normalized.get("frequency") or 1))))
    except (TypeError, ValueError):
        normalized["frequency"] = "1"
    try:
        normalized["day_of_month"] = str(max(1, min(31, int(float(normalized.get("day_of_month") or 1)))))
    except (TypeError, ValueError):
        normalized["day_of_month"] = "1"
    if normalized["active"] == "":
        normalized["active"] = "1"
    return normalized
