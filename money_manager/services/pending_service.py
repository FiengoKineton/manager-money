from __future__ import annotations

from datetime import date, timedelta

from money_manager.config import (
    CREDIT_ACCOUNT_KEYWORDS,
    CREDIT_CARD_PAYMENT_CATEGORY,
    PAYPAL_CREDIT_ALIASES,
    PAYPAL_CREDIT_ACCOUNT_VALUE,
    account_label_for_value,
    is_auxiliary_account,
)
from money_manager.repositories.pending import load_pending, mark_executed
from money_manager.repositories.transactions import append_transaction


def pending_total(rows: list[dict], include_auxiliary: bool = False) -> float:
    """Net amount expected to leave the main account.

    Expenses and investments increase the pending outflow. Pending income is
    treated as money expected to arrive, so it lowers the net outflow. Auxiliary
    accounts are skipped by default because they are tracked separately.
    """
    total = 0.0
    for tx in rows:
        if tx.get("status") != "pending":
            continue
        if not include_auxiliary and is_auxiliary_account(tx.get("account", "")):
            continue

        try:
            amount = float(tx.get("amount", 0.0))
        except (TypeError, ValueError):
            continue

        tx_type = str(tx.get("type", "expense")).lower()
        if tx_type == "income":
            total -= amount
        else:
            total += amount
    return total


def prepare_pending_for_display(rows: list[dict]) -> dict:
    """Sort pending items first, then executed items, and add UI helpers."""
    prepared = [_decorate_pending_row(row) for row in rows]
    pending_rows = sorted(
        [row for row in prepared if row["status"] == "pending"],
        key=lambda row: (row["date_due_sort"], row["category"], row["description"]),
    )
    executed_rows = sorted(
        [row for row in prepared if row["status"] != "pending"],
        key=lambda row: (row["date_due_sort"], row["category"], row["description"]),
        reverse=True,
    )

    pending_income = sum(row["amount_value"] for row in pending_rows if row["type"] == "income")
    pending_outflow = sum(row["amount_value"] for row in pending_rows if row["type"] != "income")
    auxiliary_pending = sum(row["amount_value"] for row in pending_rows if row["is_auxiliary_account"])
    next_pending_date = pending_rows[0]["date_due_str"] if pending_rows else "—"

    return {
        "all": [*pending_rows, *executed_rows],
        "pending": pending_rows,
        "executed": executed_rows,
        "pending_total": pending_total(rows, include_auxiliary=True),
        "main_pending_total": pending_total(rows, include_auxiliary=False),
        "pending_income": float(pending_income),
        "pending_outflow": float(pending_outflow),
        "auxiliary_pending": float(auxiliary_pending),
        "next_pending_date": next_pending_date,
    }


def execute_pending_by_id(tx_id: int | str, execution_date: str | None = None) -> bool:
    """Execute one open pending row and write the real transaction.

    This is intentionally manual. Opening the app should generate the queue, not
    silently mark bills as paid before you can delay or correct them.
    """
    for tx in load_pending():
        if str(tx.get("id", "")) != str(tx_id):
            continue
        if str(tx.get("status", "pending")).lower() != "pending":
            return False
        _execute_pending_row(tx, execution_date=execution_date)
        mark_executed(int(tx["id"]))
        return True
    return False


def process_pending(today: date | None = None, credit_only: bool = False) -> int:
    """Execute pending rows due up to today.

    If credit_only=True, only Credit Card / PayPal-credit pending rows
    are executed automatically. Other pending rows stay manual.
    """
    today = today or date.today()
    pending = load_pending()
    executed_count = 0

    credit_group: dict[tuple[str, str], float] = {}
    credit_ids: dict[tuple[str, str], list[int]] = {}
    other_to_execute = []

    for tx in pending:
        if tx.get("status") != "pending":
            continue

        try:
            due = date.fromisoformat(tx.get("date_due", ""))
        except ValueError:
            continue

        if due > today:
            continue

        account_value = str(tx.get("account", "")).strip().lower()
        is_credit_payment = account_value in CREDIT_ACCOUNT_KEYWORDS

        if credit_only and not is_credit_payment:
            continue

        try:
            amount = float(tx.get("amount", 0.0))
        except (TypeError, ValueError):
            amount = 0.0

        if is_credit_payment:
            group_key = (
                tx["date_due"],
                PAYPAL_CREDIT_ACCOUNT_VALUE if account_value in PAYPAL_CREDIT_ALIASES else "credit",
            )
            credit_group[group_key] = credit_group.get(group_key, 0.0) + amount
            credit_ids.setdefault(group_key, []).append(int(tx["id"]))
        else:
            other_to_execute.append(tx)

    if not credit_only:
        for tx in other_to_execute:
            _execute_pending_row(tx)
            mark_executed(int(tx["id"]))
            executed_count += 1

    for (due_date, account_value), total in credit_group.items():
        label = "PayPal" if account_value == PAYPAL_CREDIT_ACCOUNT_VALUE else "Credit card"

        append_transaction({
            "type": "expense",
            "date": due_date,
            "category": CREDIT_CARD_PAYMENT_CATEGORY,
            "sub_category": label,
            "amount": total,
            "account": account_value,
            "description": f"{label} payment ({due_date})",
        })

        for tx_id in credit_ids.get((due_date, account_value), []):
            mark_executed(tx_id)
            executed_count += 1

    return executed_count


def _execute_pending_row(tx: dict, execution_date: str | None = None) -> None:
    execution_date = execution_date or tx.get("date_due", date.today().isoformat())
    account_value = str(tx.get("account", "")).strip().lower()

    if tx.get("source") == "debt":
        from money_manager.services.debt_service import register_pending_debt_payment

        debt_tx = dict(tx)
        debt_tx["date_due"] = execution_date
        register_pending_debt_payment(debt_tx)
        return

    if account_value in CREDIT_ACCOUNT_KEYWORDS:
        label = "PayPal" if account_value in PAYPAL_CREDIT_ALIASES else "Credit card"
        append_transaction({
            "type": "expense",
            "date": execution_date,
            "category": CREDIT_CARD_PAYMENT_CATEGORY,
            "sub_category": label,
            "amount": float(tx.get("amount", 0.0)),
            "account": PAYPAL_CREDIT_ACCOUNT_VALUE if label == "PayPal" else "credit",
            "description": f"{label} payment ({execution_date})",
        })
        return

    append_transaction({
        "type": tx.get("type", "expense"),
        "date": execution_date,
        "category": tx.get("category", ""),
        "sub_category": "",
        "amount": float(tx.get("amount", 0.0)),
        "account": tx.get("account", ""),
        "description": tx.get("description", ""),
    })


def _decorate_pending_row(row: dict) -> dict:
    decorated = dict(row)
    decorated["status"] = str(decorated.get("status", "pending") or "pending").lower()
    decorated["type"] = str(decorated.get("type", "expense") or "expense").lower()
    decorated["account_label"] = account_label_for_value(decorated.get("account", ""))
    decorated["is_auxiliary_account"] = is_auxiliary_account(decorated.get("account", ""))

    try:
        amount = float(decorated.get("amount", 0.0))
    except (TypeError, ValueError):
        amount = 0.0
    decorated["amount_value"] = amount
    decorated["amount_str"] = f"€ {amount:.2f}"
    decorated["direction_label"] = "Expected income" if decorated["type"] == "income" else "Expected outflow"
    decorated["impact_tone"] = "income" if decorated["type"] == "income" else "expense"

    try:
        due = date.fromisoformat(decorated.get("date_due", ""))
    except ValueError:
        due = date.max
    decorated["date_due_sort"] = due
    decorated["date_due_str"] = "" if due == date.max else due.isoformat()

    if due == date.max:
        delay_base = date.today()
    else:
        delay_base = max(due, date.today())
    decorated["delay_date_default"] = (delay_base + timedelta(days=1)).isoformat()
    decorated["is_overdue"] = bool(due != date.max and due < date.today() and decorated["status"] == "pending")
    decorated["is_due_today"] = bool(due == date.today() and decorated["status"] == "pending")
    return decorated
