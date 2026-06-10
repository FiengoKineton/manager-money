from __future__ import annotations

from datetime import date, datetime

from money_manager.config import account_options_for_forms
from money_manager.repositories.receivables import (
    append_receivable,
    delete_receivable,
    load_receivables,
    update_receivable,
)
from money_manager.repositories.transactions import append_transaction, delete_transaction, update_transaction

DEFAULT_RECEIVABLE_INCOME_CATEGORY = "Refund"
DEFAULT_RECEIVABLE_EXPENSE_CATEGORY = "Money owed to me"


def add_receivable_from_form(form) -> None:
    amount = _amount(form.get("original_amount"))
    if amount <= 0:
        return

    start_date = form.get("start_date", date.today().isoformat()) or date.today().isoformat()
    account = form.get("account", "")
    name = form.get("name", "")
    debtor = form.get("debtor", "")
    description = form.get("description", "")

    # Register the money leaving the selected account immediately.  If the
    # account is blank/main/credit/PayPal it affects the main net; if it is a
    # liquid account it affects that account balance instead.
    linked_expense_id = append_transaction({
        "type": "expense",
        "date": start_date,
        "category": DEFAULT_RECEIVABLE_EXPENSE_CATEGORY,
        "sub_category": name or debtor,
        "amount": amount,
        "account": account,
        "description": _loan_expense_description(name, debtor, description),
    })

    append_receivable({
        "name": name,
        "debtor": debtor,
        "original_amount": amount,
        "remaining_amount": _amount(form.get("remaining_amount", amount)) or amount,
        "account": account,
        "start_date": start_date,
        "due_date": form.get("due_date", ""),
        "description": description,
        "linked_expense_transaction_id": linked_expense_id,
    })


def delete_receivable_from_form(form) -> None:
    receivable_id = _safe_int(form.get("id"))
    if receivable_id is None:
        return

    item = receivable_by_id(receivable_id)
    if item:
        linked_id = _safe_int(item.get("linked_expense_transaction_id"))
        if linked_id is not None:
            delete_transaction(linked_id, "expense")
    delete_receivable(receivable_id)


def update_receivable_from_form(form) -> None:
    receivable_id = _safe_int(form.get("id"))
    if receivable_id is None:
        return

    item = receivable_by_id(receivable_id)
    if not item:
        return

    original_amount = _amount(form.get("original_amount"))
    remaining = _amount(form.get("remaining_amount"))
    status = form.get("status", "active")
    if remaining <= 0.005:
        status = "collected"

    name = form.get("name", "")
    debtor = form.get("debtor", "")
    account = form.get("account", "")
    start_date = form.get("start_date", "") or item.get("start_date", date.today().isoformat())
    description = form.get("description", "")

    linked_id = _safe_int(item.get("linked_expense_transaction_id"))
    if linked_id is not None:
        update_transaction(linked_id, "expense", {
            "date": start_date,
            "category": DEFAULT_RECEIVABLE_EXPENSE_CATEGORY,
            "sub_category": name or debtor,
            "amount": original_amount,
            "account": account,
            "description": _loan_expense_description(name, debtor, description),
        })

    updates = {
        "name": name,
        "debtor": debtor,
        "original_amount": original_amount,
        "remaining_amount": remaining,
        "account": account,
        "start_date": start_date,
        "due_date": form.get("due_date", ""),
        "description": description,
        "status": status,
    }
    if status != "active":
        updates["closed_at"] = datetime.now().isoformat(timespec="seconds")
    update_receivable(receivable_id, updates)


def collect_receivable_from_form(form) -> None:
    receivable_id = _safe_int(form.get("id"))
    if receivable_id is None:
        return

    item = receivable_by_id(receivable_id)
    if not item:
        return

    amount = _amount(form.get("amount"))
    if amount <= 0:
        amount = _amount(item.get("remaining_amount"))

    register_receivable_collection(
        receivable_id=receivable_id,
        amount=amount,
        payment_date=form.get("date", date.today().isoformat()),
        account=form.get("account", item.get("account", "")),
        description=form.get("description", ""),
    )


def register_receivable_collection(receivable_id, amount: float, payment_date: str, account: str = "", description: str = "") -> None:
    item = receivable_by_id(receivable_id)
    if not item:
        return

    amount = min(_amount(amount), _amount(item.get("remaining_amount")))
    if amount <= 0:
        return

    append_transaction({
        "type": "income",
        "date": payment_date or date.today().isoformat(),
        "category": DEFAULT_RECEIVABLE_INCOME_CATEGORY,
        "sub_category": item.get("name", ""),
        "amount": amount,
        "account": account,
        "description": description or f"Money collected from {item.get('debtor', '')}: {item.get('name', '')}",
    })

    remaining = max(0.0, _amount(item.get("remaining_amount")) - amount)
    updates = {"remaining_amount": remaining}
    if remaining <= 0.005:
        updates["status"] = "collected"
        updates["closed_at"] = datetime.now().isoformat(timespec="seconds")
    update_receivable(int(item["id"]), updates)


def receivable_by_id(receivable_id) -> dict | None:
    for row in load_receivables():
        if str(row.get("id")) == str(receivable_id):
            return row
    return None


def overview_totals() -> dict:
    rows = load_receivables()
    active = [row for row in rows if row.get("status") == "active"]
    active_remaining = sum(_amount(row.get("remaining_amount")) for row in active)
    original_total = sum(_amount(row.get("original_amount")) for row in rows)
    collected_total = sum(
        max(0.0, _amount(row.get("original_amount")) - _amount(row.get("remaining_amount")))
        for row in rows
    )
    return {
        "active_remaining": float(active_remaining),
        "original_total": float(original_total),
        "collected_total": float(collected_total),
        "count_active": len(active),
        "count_total": len(rows),
    }


def page_context(main_net: float = 0.0, visible_liquidity: float = 0.0) -> dict:
    rows = load_receivables()
    for row in rows:
        original = _amount(row.get("original_amount"))
        remaining = _amount(row.get("remaining_amount"))
        row["original_amount"] = original
        row["remaining_amount"] = remaining
        row["collected_amount"] = max(0.0, original - remaining)
        row["progress"] = 0.0 if original <= 0 else min(100.0, row["collected_amount"] / original * 100.0)

    active = [row for row in rows if row.get("status") == "active"]
    totals = overview_totals()
    totals["main_net_if_repaid"] = float(main_net + totals["active_remaining"])
    totals["visible_liquidity_if_repaid"] = float(visible_liquidity + totals["active_remaining"])

    return {
        "receivables": rows,
        "active_receivables": active,
        "totals": totals,
        "today": date.today().isoformat(),
        "account_options": account_options_for_forms(include_credit=False),
    }


def _loan_expense_description(name: str, debtor: str, description: str) -> str:
    base = f"Loan/receivable created: {debtor or 'someone'} owes me"
    if name:
        base += f" for {name}"
    if description:
        base += f". {description}"
    return base


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
