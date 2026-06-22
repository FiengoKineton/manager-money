from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping

from money_manager.config import account_options_for_forms, normalize_account_key, MAIN_ACCOUNT_KEY
from money_manager.repositories.payables import (
    append_payable,
    delete_payable,
    load_payables,
    update_payable,
)
from money_manager.repositories.transactions import append_transaction
from money_manager.services.transaction_service import save_transaction_payload

DEFAULT_PAYABLE_EXPENSE_CATEGORY = "Payable"


def add_payable_from_form(form) -> None:
    amount = _amount(form.get("original_amount"))
    if amount <= 0:
        return

    append_payable({
        "name": form.get("name", ""),
        "payee": form.get("payee", ""),
        "original_amount": amount,
        "remaining_amount": _amount(form.get("remaining_amount", amount)) or amount,
        "category": form.get("category") or DEFAULT_PAYABLE_EXPENSE_CATEGORY,
        "account": form.get("account", ""),
        "start_date": form.get("start_date", date.today().isoformat()) or date.today().isoformat(),
        "due_date": form.get("due_date", ""),
        "description": form.get("description", ""),
    })


def delete_payable_from_form(form) -> None:
    payable_id = _safe_int(form.get("id"))
    if payable_id is None:
        return
    delete_payable(payable_id)


def update_payable_from_form(form) -> None:
    payable_id = _safe_int(form.get("id"))
    if payable_id is None:
        return

    remaining = _amount(form.get("remaining_amount"))
    status = form.get("status", "active")
    if remaining <= 0.005:
        status = "paid"

    updates = {
        "name": form.get("name", ""),
        "payee": form.get("payee", ""),
        "original_amount": _amount(form.get("original_amount")),
        "remaining_amount": remaining,
        "category": form.get("category") or DEFAULT_PAYABLE_EXPENSE_CATEGORY,
        "account": form.get("account", ""),
        "start_date": form.get("start_date", ""),
        "due_date": form.get("due_date", ""),
        "description": form.get("description", ""),
        "status": status,
    }
    if status != "active":
        updates["closed_at"] = datetime.now().isoformat(timespec="seconds")
    update_payable(payable_id, updates)


def pay_payable_from_form(form) -> None:
    payable_id = _safe_int(form.get("id"))
    if payable_id is None:
        return

    item = payable_by_id(payable_id)
    if not item:
        return

    amount = _amount(form.get("amount"))
    if amount <= 0:
        amount = _amount(item.get("remaining_amount"))

    register_payable_payment(
        payable_id=payable_id,
        amount=amount,
        payment_date=form.get("date", date.today().isoformat()),
        account=form.get("account", item.get("account", "")),
        description=form.get("description", ""),
        payment_method=form.get("account_payment_method", ""),
        insufficient_action=form.get("account_insufficient_action", ""),
    )


def register_payable_payment(
    payable_id,
    amount: float,
    payment_date: str,
    account: str = "",
    description: str = "",
    payment_method: str | None = None,
    insufficient_action: str | None = None,
    extra_tx_fields: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    item = payable_by_id(payable_id)
    if not item:
        return {"ok": False, "error": "Payable was not found."}

    requested_amount = _amount(amount)
    remaining_before = _amount(item.get("remaining_amount"))
    amount = min(requested_amount, remaining_before)
    if amount <= 0:
        return {"ok": False, "error": "Payable payment amount must be greater than zero."}

    payment_account = account if account is not None else item.get("account", "")
    tx_payload = {
        "type": "expense",
        "date": payment_date or date.today().isoformat(),
        "category": item.get("category") or DEFAULT_PAYABLE_EXPENSE_CATEGORY,
        "sub_category": item.get("name", ""),
        "amount": amount,
        "account": payment_account,
        "description": description or f"Payable payment to {item.get('payee', '')}: {item.get('name', '')}",
    }
    if extra_tx_fields:
        tx_payload.update(dict(extra_tx_fields))

    save_result = save_transaction_payload(
        tx_payload,
        payment_method=payment_method,
        insufficient_action=insufficient_action,
    )
    if isinstance(save_result, dict) and not save_result.get("ok", True):
        return save_result
    transaction_ids = save_result.get("transaction_ids", []) if isinstance(save_result, dict) else []

    # If this payable is linked to an Expense Project, attach this existing
    # transaction to the project Actuals. This is only a link, not a second payment.
    from money_manager.services.expense_project_service import attach_payable_payment_to_linked_projects

    for tx_id in transaction_ids:
        attach_payable_payment_to_linked_projects(
            payable_id=payable_id,
            transaction_id=tx_id,
            note=f"Payable payment: {item.get('name', '')}",
        )

    remaining = max(0.0, remaining_before - amount)
    updates = {"remaining_amount": remaining, "account": payment_account}
    if remaining <= 0.005:
        updates["status"] = "paid"
        updates["closed_at"] = datetime.now().isoformat(timespec="seconds")
    update_payable(int(item["id"]), updates)

    result = dict(save_result or {"ok": True})
    result.update({"ok": True, "paid_amount": amount, "remaining_amount": remaining, "payable_id": payable_id})
    return result


def payable_by_id(payable_id) -> dict | None:
    for row in load_payables():
        if str(row.get("id")) == str(payable_id):
            return row
    return None


def overview_totals() -> dict:
    rows = load_payables()
    active = [row for row in rows if row.get("status") == "active" and _amount(row.get("remaining_amount")) > 0]
    active_remaining = sum(_amount(row.get("remaining_amount")) for row in active)
    original_total = sum(_amount(row.get("original_amount")) for row in rows)
    paid_total = sum(max(0.0, _amount(row.get("original_amount")) - _amount(row.get("remaining_amount"))) for row in rows)
    main_remaining = sum(_amount(row.get("remaining_amount")) for row in active if _payable_hits_main_net(row))
    auxiliary_remaining = active_remaining - main_remaining

    return {
        "active_remaining": float(active_remaining),
        "main_remaining": float(main_remaining),
        "auxiliary_remaining": float(auxiliary_remaining),
        "original_total": float(original_total),
        "paid_total": float(paid_total),
        "count_active": len(active),
        "count_total": len(rows),
    }


def page_context(main_net: float = 0.0, visible_liquidity: float = 0.0) -> dict:
    rows = load_payables()
    for row in rows:
        original = _amount(row.get("original_amount"))
        remaining = _amount(row.get("remaining_amount"))
        row["original_amount"] = original
        row["remaining_amount"] = remaining
        row["paid_amount"] = max(0.0, original - remaining)
        row["progress"] = 0.0 if original <= 0 else min(100.0, row["paid_amount"] / original * 100.0)

    active = [row for row in rows if row.get("status") == "active" and _amount(row.get("remaining_amount")) > 0]
    totals = overview_totals()
    totals["main_net_now"] = float(main_net)
    totals["visible_liquidity_now"] = float(visible_liquidity)
    totals["main_net_if_paid_all"] = float(main_net - totals["main_remaining"])
    totals["visible_liquidity_if_paid_all"] = float(visible_liquidity - totals["active_remaining"])

    return {
        "payables": rows,
        "active_payables": active,
        "totals": totals,
        "today": date.today().isoformat(),
        "account_options": account_options_for_forms(include_credit=True),
    }


def _payable_hits_main_net(row: dict) -> bool:
    return normalize_account_key(row.get("account", "")) == MAIN_ACCOUNT_KEY


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
