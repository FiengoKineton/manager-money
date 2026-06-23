from __future__ import annotations

from datetime import datetime

from money_manager.config import (
    EXPENSE_PROJECTS_CSV,
    EXPENSE_PROJECT_MOVEMENTS_CSV,
    EXPENSE_PROJECT_PLANNED_ITEMS_CSV,
)
from money_manager.domain.constants import (
    EXPENSE_PROJECT_FIELDS,
    EXPENSE_PROJECT_MOVEMENT_FIELDS,
    EXPENSE_PROJECT_PLANNED_ITEM_FIELDS,
)
from money_manager.repositories.csv_files import append_row, next_numeric_id, read_rows, write_rows


def load_projects() -> list[dict]:
    return read_rows(EXPENSE_PROJECTS_CSV, EXPENSE_PROJECT_FIELDS)


def append_project(data: dict) -> int:
    rows = load_projects()
    project_id = next_numeric_id(rows)
    row = {
        "id": project_id,
        "name": data.get("name", ""),
        "category": data.get("category", ""),
        "description": data.get("description", ""),
        "status": data.get("status", "active") or "active",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "closed_at": data.get("closed_at", ""),
    }
    append_row(EXPENSE_PROJECTS_CSV, EXPENSE_PROJECT_FIELDS, row)
    return int(project_id)


def update_project(project_id: int, updates: dict) -> bool:
    rows = load_projects()
    found = False
    for row in rows:
        if str(row.get("id")) == str(project_id):
            row.update({key: value for key, value in updates.items() if key in EXPENSE_PROJECT_FIELDS})
            if row.get("status") != "active" and not row.get("closed_at"):
                row["closed_at"] = datetime.now().isoformat(timespec="seconds")
            found = True
            break
    if found:
        write_rows(EXPENSE_PROJECTS_CSV, EXPENSE_PROJECT_FIELDS, rows)
    return found


def delete_project(project_id: int) -> bool:
    rows = load_projects()
    kept = [row for row in rows if str(row.get("id")) != str(project_id)]
    if len(kept) == len(rows):
        return False
    write_rows(EXPENSE_PROJECTS_CSV, EXPENSE_PROJECT_FIELDS, kept)

    movements = [row for row in load_movements() if str(row.get("project_id")) != str(project_id)]
    write_rows(EXPENSE_PROJECT_MOVEMENTS_CSV, EXPENSE_PROJECT_MOVEMENT_FIELDS, movements)

    items = [row for row in load_planned_items() if str(row.get("project_id")) != str(project_id)]
    write_rows(EXPENSE_PROJECT_PLANNED_ITEMS_CSV, EXPENSE_PROJECT_PLANNED_ITEM_FIELDS, items)
    return True


def load_movements(project_id: int | None = None) -> list[dict]:
    rows = read_rows(EXPENSE_PROJECT_MOVEMENTS_CSV, EXPENSE_PROJECT_MOVEMENT_FIELDS)
    if project_id is None:
        return rows
    return [row for row in rows if str(row.get("project_id")) == str(project_id)]


def movement_exists(project_id: int, transaction_type: str, transaction_id: int) -> bool:
    return any(
        str(row.get("project_id")) == str(project_id)
        and str(row.get("transaction_type")) == str(transaction_type)
        and str(row.get("transaction_id")) == str(transaction_id)
        for row in load_movements(project_id)
    )


def append_movement(data: dict) -> int:
    rows = load_movements()
    movement_id = next_numeric_id(rows)
    row = {
        "id": movement_id,
        "project_id": data.get("project_id", ""),
        "transaction_type": data.get("transaction_type", "expense"),
        "transaction_id": data.get("transaction_id", ""),
        "source": data.get("source", "manual"),
        "note": data.get("note", ""),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    append_row(EXPENSE_PROJECT_MOVEMENTS_CSV, EXPENSE_PROJECT_MOVEMENT_FIELDS, row)
    return int(movement_id)


def delete_movement(movement_id: int) -> bool:
    rows = load_movements()
    kept = [row for row in rows if str(row.get("id")) != str(movement_id)]
    if len(kept) == len(rows):
        return False
    write_rows(EXPENSE_PROJECT_MOVEMENTS_CSV, EXPENSE_PROJECT_MOVEMENT_FIELDS, kept)
    return True


def load_planned_items(project_id: int | None = None) -> list[dict]:
    rows = read_rows(EXPENSE_PROJECT_PLANNED_ITEMS_CSV, EXPENSE_PROJECT_PLANNED_ITEM_FIELDS)
    if project_id is None:
        return rows
    return [row for row in rows if str(row.get("project_id")) == str(project_id)]


def linked_payable_exists(project_id: int, payable_id: int) -> bool:
    return any(
        str(row.get("project_id")) == str(project_id)
        and str(row.get("payable_id", "")) == str(payable_id)
        for row in load_planned_items(project_id)
    )


def append_planned_item(data: dict) -> int:
    rows = load_planned_items()
    item_id = next_numeric_id(rows)
    row = {
        "id": item_id,
        "project_id": data.get("project_id", ""),
        "name": data.get("name", ""),
        "vendor": data.get("vendor", ""),
        "original_amount": data.get("original_amount", 0),
        "remaining_amount": data.get("remaining_amount", data.get("original_amount", 0)),
        "category": data.get("category", ""),
        "sub_category": data.get("sub_category", ""),
        "account": data.get("account", ""),
        "account_id": data.get("account_id", ""),
        "account_name_snapshot": data.get("account_name_snapshot", ""),
        "preferred_payment_method_id": data.get("preferred_payment_method_id", ""),
        "preferred_payment_method_name_snapshot": data.get("preferred_payment_method_name_snapshot", ""),
        "start_date": data.get("start_date", ""),
        "due_date": data.get("due_date", ""),
        "description": data.get("description", ""),
        "status": data.get("status", "active") or "active",
        "payable_id": data.get("payable_id", ""),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "closed_at": data.get("closed_at", ""),
    }
    append_row(EXPENSE_PROJECT_PLANNED_ITEMS_CSV, EXPENSE_PROJECT_PLANNED_ITEM_FIELDS, row)
    return int(item_id)


def update_planned_item(item_id: int, updates: dict) -> bool:
    rows = load_planned_items()
    found = False
    for row in rows:
        if str(row.get("id")) == str(item_id):
            row.update({key: value for key, value in updates.items() if key in EXPENSE_PROJECT_PLANNED_ITEM_FIELDS})
            if row.get("status") != "active" and not row.get("closed_at"):
                row["closed_at"] = datetime.now().isoformat(timespec="seconds")
            found = True
            break
    if found:
        write_rows(EXPENSE_PROJECT_PLANNED_ITEMS_CSV, EXPENSE_PROJECT_PLANNED_ITEM_FIELDS, rows)
    return found


def delete_planned_item(item_id: int) -> bool:
    rows = load_planned_items()
    kept = [row for row in rows if str(row.get("id")) != str(item_id)]
    if len(kept) == len(rows):
        return False
    write_rows(EXPENSE_PROJECT_PLANNED_ITEMS_CSV, EXPENSE_PROJECT_PLANNED_ITEM_FIELDS, kept)
    return True
