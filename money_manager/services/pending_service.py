from datetime import date

from money_manager.config import CREDIT_CARD_PAYMENT_CATEGORY
from money_manager.repositories.pending import load_pending, mark_executed
from money_manager.repositories.transactions import append_transaction


def pending_total(rows: list[dict]) -> float:
    total = 0.0
    for tx in rows:
        if tx.get("status") != "pending":
            continue
        try:
            total += float(tx.get("amount", 0.0))
        except (TypeError, ValueError):
            continue
    return total


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
