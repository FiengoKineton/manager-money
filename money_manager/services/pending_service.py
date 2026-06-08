from __future__ import annotations

from datetime import date

from money_manager.config import CREDIT_CARD_PAYMENT_CATEGORY, account_label_for_value, is_auxiliary_account
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


def process_pending(today: date | None = None) -> None:
    today = today or date.today()
    pending = load_pending()

    credit_group: dict[str, float] = {}
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

        try:
            amount = float(tx.get("amount", 0.0))
        except (TypeError, ValueError):
            amount = 0.0

        if str(tx.get("account", "")).lower() == "credit":
            credit_group[tx["date_due"]] = credit_group.get(tx["date_due"], 0.0) + amount
        else:
            other_to_execute.append(tx)

    for tx in other_to_execute:
        if tx.get("source") == "debt":
            from money_manager.services.debt_service import register_pending_debt_payment

            register_pending_debt_payment(tx)
        else:
            append_transaction({
                "type": tx.get("type", "expense"),
                "date": tx.get("date_due", ""),
                "category": tx.get("category", ""),
                "sub_category": "",
                "amount": float(tx.get("amount", 0.0)),
                "account": tx.get("account", ""),
                "description": tx.get("description", ""),
            })
        mark_executed(int(tx["id"]))

    for due_date, total in credit_group.items():
        append_transaction({
            "type": "expense",
            "date": due_date,
            "category": CREDIT_CARD_PAYMENT_CATEGORY,
            "sub_category": "",
            "amount": total,
            "account": "credit",
            "description": f"Credit card payment ({due_date})",
        })

        for tx in pending:
            if (
                tx.get("status") == "pending"
                and str(tx.get("account", "")).lower() == "credit"
                and tx.get("date_due") == due_date
            ):
                mark_executed(int(tx["id"]))


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
    return decorated
