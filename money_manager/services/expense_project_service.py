from __future__ import annotations

from datetime import date, datetime

import pandas as pd

from money_manager.config import MAIN_ACCOUNT_KEY, account_options_for_forms, categories_for, normalize_account_key
from money_manager.repositories.expense_projects import (
    append_movement,
    append_planned_item,
    append_project,
    delete_movement,
    delete_planned_item,
    delete_project,
    linked_payable_exists,
    load_movements,
    load_planned_items,
    load_projects,
    movement_exists,
    update_planned_item,
    update_project,
)
from money_manager.repositories.payables import load_payables
from money_manager.repositories.transactions import append_transaction
from money_manager.services.transaction_service import save_transaction_payload
from money_manager.services.account_service import auxiliary_total, main_account_transactions
from money_manager.services.transaction_service import load_transactions
from money_manager.utils.stats import summary_totals

DEFAULT_PROJECT_CATEGORY = "Construction"


def add_project_from_form(form) -> int | None:
    name = str(form.get("name", "")).strip()
    if not name:
        return None
    return append_project({
        "name": name,
        "category": form.get("category") or DEFAULT_PROJECT_CATEGORY,
        "description": form.get("description", ""),
        "status": form.get("status", "active") or "active",
    })


def update_project_from_form(form) -> None:
    project_id = _safe_int(form.get("project_id"))
    if project_id is None:
        return
    updates = {
        "name": form.get("name", ""),
        "category": form.get("category") or DEFAULT_PROJECT_CATEGORY,
        "description": form.get("description", ""),
        "status": form.get("status", "active") or "active",
    }
    if updates["status"] != "active":
        updates["closed_at"] = datetime.now().isoformat(timespec="seconds")
    update_project(project_id, updates)


def delete_project_from_form(form) -> None:
    project_id = _safe_int(form.get("project_id"))
    if project_id is not None:
        delete_project(project_id)


def project_by_id(project_id: int) -> dict | None:
    for project in load_projects():
        if str(project.get("id")) == str(project_id):
            return project
    return None


def add_planned_item_from_form(project_id: int, form) -> None:
    amount = _amount(form.get("original_amount"))
    if amount <= 0:
        return
    append_planned_item({
        "project_id": project_id,
        "name": form.get("name", ""),
        "vendor": form.get("vendor", ""),
        "original_amount": amount,
        "remaining_amount": _amount(form.get("remaining_amount", amount)) or amount,
        "category": form.get("category") or _project_category(project_id),
        "sub_category": form.get("sub_category", ""),
        "account": form.get("account", ""),
        "start_date": form.get("start_date", date.today().isoformat()) or date.today().isoformat(),
        "due_date": form.get("due_date", ""),
        "description": form.get("description", ""),
        "status": "active",
        "payable_id": "",
    })


def link_payable_to_project_from_form(project_id: int, form) -> None:
    """Mirror a Payables row inside the project forecast without paying it again."""
    payable_id = _safe_int(form.get("payable_id"))
    if payable_id is None:
        return
    payable = _payable_by_id(payable_id)
    if not payable:
        return

    if not linked_payable_exists(project_id, payable_id):
        append_planned_item({
            "project_id": project_id,
            "name": payable.get("name", ""),
            "vendor": payable.get("payee", ""),
            "original_amount": _amount(payable.get("original_amount")),
            "remaining_amount": _amount(payable.get("remaining_amount")),
            "category": payable.get("category") or _project_category(project_id),
            "sub_category": form.get("sub_category") or "Linked payable",
            "account": payable.get("account", ""),
            "start_date": payable.get("start_date", "") or date.today().isoformat(),
            "due_date": payable.get("due_date", ""),
            "description": payable.get("description", ""),
            "status": _payable_status(payable),
            "payable_id": payable_id,
            "closed_at": payable.get("closed_at", ""),
        })

    _auto_attach_existing_payable_transactions(project_id, payable)


def update_planned_item_from_form(form) -> None:
    item_id = _safe_int(form.get("item_id"))
    if item_id is None:
        return
    item = planned_item_by_id(item_id)
    if item and _safe_int(item.get("payable_id")) is not None:
        # Payable links are read-only mirrors. Edit/pay from Payables only.
        return

    remaining = _amount(form.get("remaining_amount"))
    status = form.get("status", "active") or "active"
    if remaining <= 0.005:
        status = "paid"
    updates = {
        "name": form.get("name", ""),
        "vendor": form.get("vendor", ""),
        "original_amount": _amount(form.get("original_amount")),
        "remaining_amount": remaining,
        "category": form.get("category", ""),
        "sub_category": form.get("sub_category", ""),
        "account": form.get("account", ""),
        "start_date": form.get("start_date", ""),
        "due_date": form.get("due_date", ""),
        "description": form.get("description", ""),
        "status": status,
    }
    if status != "active":
        updates["closed_at"] = datetime.now().isoformat(timespec="seconds")
    update_planned_item(item_id, updates)


def delete_planned_item_from_form(form) -> None:
    item_id = _safe_int(form.get("item_id"))
    if item_id is not None:
        delete_planned_item(item_id)


def attach_transaction_from_form(project_id: int, form) -> None:
    raw_key = str(form.get("transaction_key", "")).strip()
    if not raw_key or ":" not in raw_key:
        return
    tx_type, tx_id_raw = raw_key.split(":", 1)
    tx_id = _safe_int(tx_id_raw)
    if tx_id is None or movement_exists(project_id, tx_type, tx_id):
        return
    if _transaction_by_type_and_id(tx_type, tx_id) is None:
        return
    append_movement({
        "project_id": project_id,
        "transaction_type": tx_type,
        "transaction_id": tx_id,
        "source": "manual",
        "note": form.get("note", ""),
    })


def attach_payable_payment_to_linked_projects(payable_id, transaction_id, note: str = "") -> int:
    """Attach one already-created payable expense to each linked project.

    This creates only project movement links. It never creates a second expense.
    """
    payable_id_int = _safe_int(payable_id)
    transaction_id_int = _safe_int(transaction_id)
    if payable_id_int is None or transaction_id_int is None:
        return 0

    attached_count = 0
    for item in load_planned_items():
        if str(item.get("payable_id", "")) != str(payable_id_int):
            continue
        project_id = _safe_int(item.get("project_id"))
        if project_id is None or movement_exists(project_id, "expense", transaction_id_int):
            continue
        append_movement({
            "project_id": project_id,
            "transaction_type": "expense",
            "transaction_id": transaction_id_int,
            "source": "payable_payment",
            "note": note or f"Payable payment: {item.get('name', '')}",
        })
        attached_count += 1
    return attached_count


def detach_movement_from_form(form) -> None:
    movement_id = _safe_int(form.get("movement_id"))
    if movement_id is not None:
        delete_movement(movement_id)


def pay_planned_item_from_form(project_id: int, form) -> None:
    item_id = _safe_int(form.get("item_id"))
    if item_id is None:
        return
    item = planned_item_by_id(item_id)
    if not item or str(item.get("project_id")) != str(project_id):
        return
    if _safe_int(item.get("payable_id")) is not None:
        # Pay linked payables only from Payables; the project mirrors them.
        return

    amount = _amount(form.get("amount"))
    if amount <= 0:
        amount = _amount(item.get("remaining_amount"))
    amount = min(amount, _amount(item.get("remaining_amount")))
    if amount <= 0:
        return

    save_result = save_transaction_payload({
        "type": "expense",
        "date": form.get("date") or date.today().isoformat(),
        "category": item.get("category") or _project_category(project_id),
        "sub_category": item.get("sub_category") or item.get("name", ""),
        "amount": amount,
        "account": form.get("account", item.get("account", "")),
        "description": form.get("description") or f"Project payment: {item.get('name', '')}",
    })
    for tx_id in (save_result.get("transaction_ids", []) if isinstance(save_result, dict) else []):
        append_movement({
            "project_id": project_id,
            "transaction_type": "expense",
            "transaction_id": tx_id,
            "source": "planned_payment",
            "note": item.get("name", ""),
        })

    remaining = max(0.0, _amount(item.get("remaining_amount")) - amount)
    updates = {"remaining_amount": remaining, "account": form.get("account", item.get("account", ""))}
    if remaining <= 0.005:
        updates["status"] = "paid"
        updates["closed_at"] = datetime.now().isoformat(timespec="seconds")
    update_planned_item(item_id, updates)


def planned_item_by_id(item_id: int) -> dict | None:
    for item in load_planned_items():
        if str(item.get("id")) == str(item_id):
            return item
    return None


def overview_context() -> dict:
    df = load_transactions()
    projects = [_enrich_project_summary(project, df) for project in load_projects()]
    active_projects = [project for project in projects if project.get("status") == "active"]
    totals = {
        "actual_spent": sum(project["actual_spent"] for project in projects),
        "actual_income": sum(project["actual_income"] for project in projects),
        "actual_net_cost": sum(project["actual_net_cost"] for project in projects),
        "remaining_expected": sum(project["remaining_expected"] for project in active_projects),
        "forecast_total": sum(project["forecast_total"] for project in active_projects),
        "forecast_net_total": sum(project["forecast_net_total"] for project in active_projects),
        "active_count": len(active_projects),
        "count": len(projects),
    }
    return {"projects": projects, "totals": totals, "expense_categories": categories_for("expense"), "default_category": DEFAULT_PROJECT_CATEGORY}


def detail_context(project_id: int) -> dict | None:
    project = project_by_id(project_id)
    if not project:
        return None
    df = load_transactions()
    project = _enrich_project_summary(project, df)
    actual_movements = _project_actual_movements(project_id, df)
    planned_items = _project_planned_items(project_id)
    main_totals = summary_totals(main_account_transactions(df))
    visible_liquidity = main_totals["net"] + auxiliary_total(df)
    remaining_expected = float(project["remaining_expected"])
    main_remaining = sum(
        item["remaining_amount"] for item in planned_items
        if item.get("status") == "active" and normalize_account_key(item.get("account", "")) == MAIN_ACCOUNT_KEY
    )
    return {
        "project": project,
        "actual_movements": actual_movements,
        "planned_items": planned_items,
        "transaction_candidates": _transaction_candidates(project, df, actual_movements),
        "payable_candidates": _payable_link_candidates(project_id),
        "today": date.today().isoformat(),
        "expense_categories": categories_for("expense"),
        "account_options": account_options_for_forms(include_credit=True),
        "totals": {
            "main_net_now": float(main_totals["net"]),
            "visible_liquidity_now": float(visible_liquidity),
            "main_net_if_remaining_paid": float(main_totals["net"] - main_remaining),
            "visible_liquidity_if_remaining_paid": float(visible_liquidity - remaining_expected),
        },
    }


def _enrich_project_summary(project: dict, df: pd.DataFrame) -> dict:
    project = dict(project)
    project_id = _safe_int(project.get("id")) or 0
    actual = _project_actual_movements(project_id, df)
    planned = _project_planned_items(project_id)
    actual_spent = sum(row["amount"] for row in actual if row.get("transaction_type") == "expense")
    actual_income = sum(row["amount"] for row in actual if row.get("transaction_type") == "income")
    actual_net_cost = actual_spent - actual_income
    planned_original = sum(row["original_amount"] for row in planned)
    planned_remaining = sum(row["remaining_amount"] for row in planned if row.get("status") == "active")
    planned_paid = sum(row["paid_amount"] for row in planned)
    forecast_total = actual_spent + planned_remaining
    forecast_net_total = actual_net_cost + planned_remaining
    project.update({
        "actual_spent": float(actual_spent),
        "actual_income": float(actual_income),
        "actual_net_cost": float(actual_net_cost),
        "planned_original": float(planned_original),
        "planned_paid": float(planned_paid),
        "remaining_expected": float(planned_remaining),
        "forecast_total": float(forecast_total),
        "forecast_net_total": float(forecast_net_total),
        "movement_count": len(actual),
        "income_movement_count": sum(1 for row in actual if row.get("transaction_type") == "income"),
        "expense_movement_count": sum(1 for row in actual if row.get("transaction_type") == "expense"),
        "planned_count": len(planned),
        "linked_payable_count": sum(1 for row in planned if row.get("linked_payable")),
        "progress": 0.0 if forecast_total <= 0 else min(100.0, actual_spent / forecast_total * 100.0),
    })
    return project


def _project_actual_movements(project_id: int, df: pd.DataFrame) -> list[dict]:
    rows = []
    for movement in load_movements(project_id):
        row = _transaction_by_type_and_id(movement.get("transaction_type"), movement.get("transaction_id"), df=df)
        if row is None:
            continue
        amount = _amount(row.get("amount"))
        tx_type = str(row.get("type", movement.get("transaction_type", ""))).casefold()
        if tx_type not in {"expense", "income"}:
            continue
        source = movement.get("source", "manual")
        rows.append({
            "movement_id": movement.get("id"),
            "transaction_id": movement.get("transaction_id"),
            "transaction_type": tx_type,
            "type_label": "Income" if tx_type == "income" else "Expense",
            "amount_class": "income" if tx_type == "income" else "expense",
            "amount_sign": "+" if tx_type == "income" else "-",
            "date": _date_str(row.get("date")),
            "category": _clean(row.get("category", "")),
            "sub_category": _clean(row.get("sub_category", "")),
            "account": _clean(row.get("account", "")),
            "description": _clean(row.get("description", "")),
            "amount": amount,
            "signed_amount": amount if tx_type == "income" else -amount,
            "source": source,
            "source_label": _movement_source_label(source),
            "note": movement.get("note", ""),
        })
    return sorted(rows, key=lambda item: item.get("date", ""), reverse=True)


def _project_planned_items(project_id: int) -> list[dict]:
    payables = {_safe_int(row.get("id")): row for row in load_payables() if _safe_int(row.get("id")) is not None}
    rows = []
    for item in load_planned_items(project_id):
        payable_id = _safe_int(item.get("payable_id"))
        linked = payable_id is not None
        payable = payables.get(payable_id) if linked else None
        source = payable if payable else item
        original = _amount(source.get("original_amount"))
        remaining = _amount(source.get("remaining_amount"))
        paid = max(0.0, original - remaining)
        status = _payable_status(source) if linked and payable else (item.get("status", "active") or "active")
        if remaining <= 0.005 and status == "active":
            status = "paid"
        if linked and payable is None:
            status = "missing"
        rows.append({
            **item,
            "name": source.get("name", item.get("name", "")),
            "vendor": source.get("payee", item.get("vendor", "")) if linked else item.get("vendor", ""),
            "original_amount": original,
            "remaining_amount": remaining,
            "paid_amount": paid,
            "category": source.get("category", item.get("category", "")),
            "sub_category": item.get("sub_category", "") or ("Linked payable" if linked else ""),
            "account": source.get("account", item.get("account", "")),
            "start_date": source.get("start_date", item.get("start_date", "")),
            "due_date": source.get("due_date", item.get("due_date", "")),
            "description": source.get("description", item.get("description", "")),
            "status": status,
            "progress": 0.0 if original <= 0 else min(100.0, paid / original * 100.0),
            "linked_payable": linked,
            "payable_found": bool(payable) if linked else True,
            "payable_id": payable_id or "",
            "source_label": "Linked payable" if linked else "Planned item",
        })
    return sorted(rows, key=lambda item: (item.get("status") != "active", item.get("due_date") or "9999-99-99"))


def _payable_link_candidates(project_id: int) -> list[dict]:
    linked_ids = {_safe_int(item.get("payable_id")) for item in load_planned_items(project_id) if _safe_int(item.get("payable_id")) is not None}
    candidates = []
    for payable in load_payables():
        payable_id = _safe_int(payable.get("id"))
        if payable_id is None or payable_id in linked_ids:
            continue
        original = _amount(payable.get("original_amount"))
        remaining = _amount(payable.get("remaining_amount"))
        paid = max(0.0, original - remaining)
        status = _payable_status(payable)
        parts = [_clean(payable.get("name", "Untitled payable")), _clean(payable.get("payee", "")), f"€ {paid:.2f} paid / € {remaining:.2f} left", status.title()]
        candidates.append({**payable, "id": payable_id, "original_amount": original, "remaining_amount": remaining, "paid_amount": paid, "status": status, "label": " · ".join(p for p in parts if p)})
    return sorted(candidates, key=lambda item: (item.get("status") != "active", str(item.get("name", "")).casefold()))


def _transaction_candidates(project: dict, df: pd.DataFrame, already_attached: list[dict]) -> list[dict]:
    if df.empty:
        return []
    attached = {(str(row.get("transaction_type")), str(row.get("transaction_id"))) for row in already_attached}
    project_category = str(project.get("category", "")).casefold()
    project_name = str(project.get("name", "")).casefold()
    tx_type_series = df.get("type", pd.Series(dtype=str)).astype(str).str.casefold()
    movements = df[tx_type_series.isin(["expense", "income"])].copy()
    if movements.empty:
        return []
    movements["date_sort"] = pd.to_datetime(movements["date"], errors="coerce")
    category_text = movements["category"].fillna("").astype(str).str.casefold()
    sub_text = movements["sub_category"].fillna("").astype(str).str.casefold()
    desc_text = movements["description"].fillna("").astype(str).str.casefold()
    movements["category_match"] = category_text.eq(project_category)
    movements["project_text_match"] = False
    if project_name:
        movements["project_text_match"] = desc_text.str.contains(project_name, regex=False) | sub_text.str.contains(project_name, regex=False)
    movements = movements.sort_values(by=["category_match", "project_text_match", "date_sort"], ascending=[False, False, False]).head(200)
    candidates = []
    for _, row in movements.iterrows():
        tx_type = str(row.get("type", "expense")).casefold()
        tx_id = str(row.get("id", ""))
        if (tx_type, tx_id) in attached:
            continue
        amount = _amount(row.get("amount"))
        label = f"{'Income +' if tx_type == 'income' else 'Expense -'} · {_date_str(row.get('date'))} · € {amount:.2f} · {_clean(row.get('category', ''))}"
        sub = _clean(row.get("sub_category", ""))
        desc = _clean(row.get("description", ""))
        if sub:
            label += f" / {sub}"
        if desc:
            label += f" · {desc[:60]}"
        candidates.append({"key": f"{tx_type}:{tx_id}", "label": label, "amount": amount, "type": tx_type, "category_match": bool(row.get("category_match")), "project_text_match": bool(row.get("project_text_match"))})
    return candidates


def _auto_attach_existing_payable_transactions(project_id: int, payable: dict) -> int:
    df = load_transactions()
    if df.empty:
        return 0
    name = _clean(payable.get("name", "")).casefold()
    payee = _clean(payable.get("payee", "")).casefold()
    category = _clean(payable.get("category", "")).casefold()
    if not name:
        return 0
    tx_type_series = df.get("type", pd.Series(dtype=str)).astype(str).str.casefold()
    expenses = df[tx_type_series.eq("expense")].copy()
    attached_count = 0
    for _, row in expenses.iterrows():
        tx_id = _safe_int(row.get("id"))
        if tx_id is None or movement_exists(project_id, "expense", tx_id):
            continue
        row_category = _clean(row.get("category", "")).casefold()
        row_sub = _clean(row.get("sub_category", "")).casefold()
        row_description = _clean(row.get("description", "")).casefold()
        haystack = " ".join([row_category, row_sub, row_description])
        name_match = name in haystack or row_sub == name
        payee_match = bool(payee and payee in haystack)
        payable_marker = "payable payment" in haystack
        category_match = bool(category and row_category == category)
        if name_match and (payable_marker or payee_match or category_match):
            append_movement({"project_id": project_id, "transaction_type": "expense", "transaction_id": tx_id, "source": "payable_payment", "note": f"Payable payment: {payable.get('name', '')}"})
            attached_count += 1
    return attached_count


def _transaction_by_type_and_id(tx_type, tx_id, df: pd.DataFrame | None = None) -> dict | None:
    df = load_transactions() if df is None else df
    if df.empty:
        return None
    tx_type = str(tx_type)
    tx_id = str(int(float(tx_id))) if str(tx_id).replace('.', '', 1).isdigit() else str(tx_id)
    for _, row in df.iterrows():
        row_type = str(row.get("type", ""))
        row_id = str(row.get("id", ""))
        try:
            row_id_clean = str(int(float(row_id)))
        except (TypeError, ValueError):
            row_id_clean = row_id
        if row_type == tx_type and row_id_clean == tx_id:
            return row.to_dict()
    return None


def _payable_by_id(payable_id: int) -> dict | None:
    for payable in load_payables():
        if str(payable.get("id")) == str(payable_id):
            return payable
    return None


def _payable_status(payable: dict) -> str:
    status = str(payable.get("status", "") or "").strip().casefold()
    if status:
        return status
    return "active" if _amount(payable.get("remaining_amount")) > 0.005 else "paid"


def _movement_source_label(source: str) -> str:
    labels = {"planned_payment": "Planned payment", "payable_payment": "Payable payment", "manual": "Manual link"}
    return labels.get(str(source or "manual"), str(source or "manual").replace("_", " ").title())


def _project_category(project_id: int) -> str:
    project = project_by_id(project_id) or {}
    return project.get("category") or DEFAULT_PROJECT_CATEGORY


def _date_str(value) -> str:
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return "" if str(value) == "nan" else str(value or "")


def _clean(value) -> str:
    return "" if str(value) == "nan" else str(value or "")


def _safe_int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _amount(value) -> float:
    try:
        return max(0.0, float(str(value or 0).replace(",", ".")))
    except (TypeError, ValueError):
        return 0.0
