from __future__ import annotations

from datetime import date, datetime

from money_manager.repositories.receivables import (
    append_receivable,
    delete_receivable,
    load_receivables,
    update_receivable,
)
from money_manager.repositories.transactions import delete_transaction, update_transaction
from money_manager.services.payment_form_service import account_options_for_payment_forms, payment_form_context, snapshot_account, snapshot_payment_method
from money_manager.services.transaction_service import save_transaction_payload

DEFAULT_RECEIVABLE_INCOME_CATEGORY = "Refund"
DEFAULT_RECEIVABLE_EXPENSE_CATEGORY = "Money owed to me"


def add_receivable_from_form(form) -> None:
    amount = _amount(form.get("original_amount"))
    if amount <= 0:
        return

    start_date = form.get("start_date", date.today().isoformat()) or date.today().isoformat()
    account = form.get("account_id") or form.get("account", "")
    payment_method_id = form.get("payment_method_id") or form.get("preferred_payment_method_id") or form.get("account_payment_method", "")
    name = form.get("name", "")
    debtor = form.get("debtor", "")
    description = form.get("description", "")

    # Register the money leaving the selected account immediately.  If the
    # account is blank/main/credit it affects the main net; if it is a
    # liquid account it affects that account balance instead.
    save_result = save_transaction_payload(
        {
            "type": "expense",
            "date": start_date,
            "category": DEFAULT_RECEIVABLE_EXPENSE_CATEGORY,
            "sub_category": name or debtor,
            "amount": amount,
            "account": form.get("account", "") or account,
            "account_id": account,
            "payment_method_id": payment_method_id,
            "description": _loan_expense_description(name, debtor, description),
        },
        account_id=account,
        payment_method_id=payment_method_id,
        payment_method=form.get("account_payment_method", ""),
        insufficient_action=form.get("account_insufficient_action", ""),
    )
    linked_ids = save_result.get("transaction_ids", []) if isinstance(save_result, dict) else []
    linked_expense_id = linked_ids[0] if linked_ids else ""

    new_id = append_receivable({
        "name": name,
        "debtor": debtor,
        "original_amount": amount,
        "remaining_amount": _amount(form.get("remaining_amount", amount)) or amount,
        "account": form.get("account", "") or account,
        **snapshot_account(account),
        "preferred_payment_method_id": snapshot_payment_method(payment_method_id)["payment_method_id"],
        "preferred_payment_method_name_snapshot": snapshot_payment_method(payment_method_id)["payment_method_name_snapshot"],
        "start_date": start_date,
        "due_date": form.get("due_date", ""),
        "description": description,
        "linked_expense_transaction_id": linked_expense_id,
    })
    if linked_expense_id:
        update_transaction(linked_expense_id, "expense", {
            "linked_object_type": "receivable",
            "linked_object_id": str(new_id),
            "linked_object_name": name,
        })
    try:
        from money_manager.services.timeline_service import record_created, record_event

        record_created("receivable", new_id, name)
        if linked_expense_id:
            record_event("receivable", new_id, "payment_added", f"Initial money out: €{amount:.2f}", "Receivable creation expense was recorded.", amount=amount, transaction_type="expense", transaction_id=linked_expense_id, account_id=account)
    except Exception:
        pass


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
    try:
        from money_manager.services.timeline_service import record_deleted

        record_deleted("receivable", receivable_id, (item or {}).get("name", ""))
    except Exception:
        pass


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
    account = form.get("account_id") or form.get("account", "")
    payment_method_id = form.get("payment_method_id") or form.get("preferred_payment_method_id") or form.get("account_payment_method", "")
    start_date = form.get("start_date", "") or item.get("start_date", date.today().isoformat())
    description = form.get("description", "")

    linked_id = _safe_int(item.get("linked_expense_transaction_id"))
    if linked_id is not None:
        update_transaction(linked_id, "expense", {
            "date": start_date,
            "category": DEFAULT_RECEIVABLE_EXPENSE_CATEGORY,
            "sub_category": name or debtor,
            "amount": original_amount,
            "account": form.get("account", "") or account,
            "account_id": account,
            "payment_method_id": payment_method_id,
            "description": _loan_expense_description(name, debtor, description),
        })

    updates = {
        "name": name,
        "debtor": debtor,
        "original_amount": original_amount,
        "remaining_amount": remaining,
        "account": form.get("account", "") or account,
        **snapshot_account(account),
        "preferred_payment_method_id": snapshot_payment_method(payment_method_id)["payment_method_id"],
        "preferred_payment_method_name_snapshot": snapshot_payment_method(payment_method_id)["payment_method_name_snapshot"],
        "start_date": start_date,
        "due_date": form.get("due_date", ""),
        "description": description,
        "status": status,
    }
    if status != "active":
        updates["closed_at"] = datetime.now().isoformat(timespec="seconds")
    update_receivable(receivable_id, updates)
    try:
        from money_manager.services.timeline_service import record_update_diff

        record_update_diff("receivable", receivable_id, item, {**(item or {}), **updates})
    except Exception:
        pass


def duplicate_receivable_from_form(form) -> None:
    receivable_id = _safe_int(form.get("id"))
    if receivable_id is None:
        return
    source = receivable_by_id(receivable_id)
    if not source:
        return
    new_id = append_receivable({
        "name": f"Copy of {source.get('name', '')}".strip(),
        "debtor": source.get("debtor", ""),
        "original_amount": _amount(source.get("original_amount")),
        "remaining_amount": _amount(source.get("remaining_amount")),
        "account": source.get("account", ""),
        "account_id": source.get("account_id", ""),
        "account_name_snapshot": source.get("account_name_snapshot", ""),
        "preferred_payment_method_id": source.get("preferred_payment_method_id", ""),
        "preferred_payment_method_name_snapshot": source.get("preferred_payment_method_name_snapshot", ""),
        "start_date": date.today().isoformat(),
        "due_date": source.get("due_date", ""),
        "description": source.get("description", ""),
        "status": "active",
    })
    try:
        from money_manager.services.timeline_service import record_created, record_event

        record_created("receivable", new_id, f"Copy of {source.get('name', '')}")
        record_event("receivable", new_id, "duplicated", f"Duplicated from {source.get('name', '')}")
    except Exception:
        pass


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
        account=form.get("account_id") or form.get("account") or item.get("account_id") or item.get("account", ""),
        account_id=form.get("account_id") or item.get("account_id") or form.get("account", ""),
        description=form.get("description", ""),
    )


def register_receivable_collection(receivable_id, amount: float, payment_date: str, account: str = "", description: str = "", account_id: str | None = None) -> None:
    item = receivable_by_id(receivable_id)
    if not item:
        return

    amount = min(_amount(amount), _amount(item.get("remaining_amount")))
    if amount <= 0:
        return

    effective_account_id = account_id or account or item.get("account_id") or item.get("account", "")
    save_result = save_transaction_payload({
        "type": "income",
        "date": payment_date or date.today().isoformat(),
        "category": DEFAULT_RECEIVABLE_INCOME_CATEGORY,
        "sub_category": item.get("name", ""),
        "amount": amount,
        "account": account or effective_account_id,
        "account_id": effective_account_id,
        "description": description or f"Money collected from {item.get('debtor', '')}: {item.get('name', '')}",
        "linked_object_type": "receivable",
        "linked_object_id": str(item.get("id", receivable_id)),
        "linked_object_name": item.get("name", ""),
    }, account_id=effective_account_id)

    remaining_before = _amount(item.get("remaining_amount"))
    remaining = max(0.0, remaining_before - amount)
    updates = {"remaining_amount": remaining}
    if remaining <= 0.005:
        updates["status"] = "collected"
        updates["closed_at"] = datetime.now().isoformat(timespec="seconds")
    update_receivable(int(item["id"]), updates)
    try:
        from money_manager.services.timeline_service import record_amount_change, record_payment, record_status_change

        transaction_ids = save_result.get("transaction_ids", []) if isinstance(save_result, dict) else []
        tx_id = transaction_ids[0] if transaction_ids else ""
        record_payment(
            "receivable",
            item.get("id", receivable_id),
            amount,
            effective_account_id,
            "income",
            tx_id,
            title=f"Collected €{amount:.2f} into {effective_account_id or 'selected account'}",
        )
        record_amount_change("receivable", item.get("id", receivable_id), "remaining_amount", remaining_before, remaining)
        if updates.get("status"):
            record_status_change("receivable", item.get("id", receivable_id), item.get("status", ""), updates.get("status", ""))
    except Exception:
        pass


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
        try:
            from money_manager.services.timeline_service import enrich_object_row

            enrich_object_row(row, "receivable")
        except Exception:
            row.setdefault("timeline_text", "No timeline events yet.")
            row.setdefault("payment_history_text", "No payments recorded yet.")
            row.setdefault("linked_transactions_text", "No linked transactions yet.")

    active = [row for row in rows if row.get("status") == "active"]
    totals = overview_totals()
    totals["main_net_if_repaid"] = float(main_net + totals["active_remaining"])
    totals["visible_liquidity_if_repaid"] = float(visible_liquidity + totals["active_remaining"])

    form_ctx = payment_form_context("income")

    return {
        "receivables": rows,
        "active_receivables": active,
        "totals": totals,
        "today": date.today().isoformat(),
        "account_options": account_options_for_payment_forms(include_credit=False),
        **form_ctx,
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
