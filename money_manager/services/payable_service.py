from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Mapping

from money_manager.config import MAIN_ACCOUNT_KEY, normalize_account_key
from money_manager.repositories.payables import (
    append_payable,
    delete_payable,
    load_payables,
    update_payable,
)
from money_manager.services.payment_form_service import (
    account_options_for_payment_forms,
    payment_form_context,
    snapshot_account,
    snapshot_payment_method,
)
from money_manager.services.transaction_service import save_transaction_payload

DEFAULT_PAYABLE_EXPENSE_CATEGORY = "Payable"


def _preferred_fields_from_form(form) -> dict[str, Any]:
    account_id = form.get("account_id") or form.get("account", "")
    payment_method_id = form.get("preferred_payment_method_id") or form.get("payment_method_id") or form.get("account_payment_method", "")
    return {
        **snapshot_account(account_id),
        "account": form.get("account", "") or account_id,
        "preferred_payment_method_id": snapshot_payment_method(payment_method_id)["payment_method_id"],
        "preferred_payment_method_name_snapshot": snapshot_payment_method(payment_method_id)["payment_method_name_snapshot"],
    }


def add_payable_from_form(form) -> None:
    amount = _amount(form.get("original_amount"))
    if amount <= 0:
        return

    new_id = append_payable({
        "name": form.get("name", ""),
        "payee": form.get("payee", ""),
        "original_amount": amount,
        "remaining_amount": _amount(form.get("remaining_amount", amount)) or amount,
        "category": form.get("category") or DEFAULT_PAYABLE_EXPENSE_CATEGORY,
        "start_date": form.get("start_date", date.today().isoformat()) or date.today().isoformat(),
        "due_date": form.get("due_date", ""),
        "description": form.get("description", ""),
        **_preferred_fields_from_form(form),
    })
    try:
        from money_manager.services.timeline_service import record_created

        record_created("payable", new_id, form.get("name", ""))
    except Exception:
        pass


def delete_payable_from_form(form) -> None:
    payable_id = _safe_int(form.get("id"))
    if payable_id is None:
        return
    before = payable_by_id(payable_id)
    delete_payable(payable_id)
    try:
        from money_manager.services.timeline_service import record_deleted

        record_deleted("payable", payable_id, (before or {}).get("name", ""))
    except Exception:
        pass


def _linked_payable_transactions(payable_id) -> list[dict]:
    try:
        from money_manager.services.transaction_service import load_transactions
        frame = load_transactions()
        if frame.empty:
            return []
        linked = frame[(frame.get("linked_object_type", "").fillna("").astype(str) == "payable") & (frame.get("linked_object_id", "").fillna("").astype(str) == str(payable_id))]
        rows = linked.sort_values("date").to_dict("records")
        result = []
        for row in rows:
            result.append({
                "row_index": int(row.get("row_index", row.get("id", 0)) or 0),
                "date": str(row.get("date"))[:10],
                "amount": _amount(row.get("amount")),
                "description": str(row.get("description") or ""),
                "transaction_uid": str(row.get("transaction_uid") or ""),
            })
        return result
    except Exception:
        return []


def _paid_amount_from_transactions(payable_id) -> float:
    return sum(_amount(row.get("amount")) for row in _linked_payable_transactions(payable_id))


def update_payable_from_form(form) -> None:
    payable_id = _safe_int(form.get("id"))
    if payable_id is None:
        return

    before = payable_by_id(payable_id)
    original_amount = _amount(form.get("original_amount"))
    paid_amount = _paid_amount_from_transactions(payable_id)
    # Transaction history is authoritative: editing the payable total must not
    # rewrite payments that have already been recorded.
    remaining = max(0.0, original_amount - paid_amount)
    status = form.get("status", "active")
    if remaining <= 0.005:
        status = "paid"

    updates = {
        "name": form.get("name", ""),
        "payee": form.get("payee", ""),
        "original_amount": original_amount,
        "remaining_amount": remaining,
        "category": form.get("category") or DEFAULT_PAYABLE_EXPENSE_CATEGORY,
        "start_date": form.get("start_date", ""),
        "due_date": form.get("due_date", ""),
        "description": form.get("description", ""),
        "status": status,
        **_preferred_fields_from_form(form),
    }
    if status != "active":
        updates["closed_at"] = datetime.now().isoformat(timespec="seconds")
    update_payable(payable_id, updates)
    try:
        from money_manager.services.timeline_service import record_update_diff

        record_update_diff("payable", payable_id, before, {**(before or {}), **updates})
    except Exception:
        pass


def duplicate_payable_from_form(form) -> None:
    payable_id = _safe_int(form.get("id"))
    if payable_id is None:
        return
    source = payable_by_id(payable_id)
    if not source:
        return
    new_id = append_payable({
        "name": f"Copy of {source.get('name', '')}".strip(),
        "payee": source.get("payee", ""),
        "original_amount": _amount(source.get("original_amount")),
        "remaining_amount": _amount(source.get("remaining_amount")),
        "category": source.get("category") or DEFAULT_PAYABLE_EXPENSE_CATEGORY,
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

        record_created("payable", new_id, f"Copy of {source.get('name', '')}")
        record_event("payable", new_id, "duplicated", f"Duplicated from {source.get('name', '')}")
    except Exception:
        pass


def pay_payable_from_form(form) -> dict[str, Any] | None:
    payable_id = _safe_int(form.get("id"))
    if payable_id is None:
        return None

    item = payable_by_id(payable_id)
    if not item:
        return None

    amount = _amount(form.get("amount"))
    if amount <= 0:
        amount = _amount(item.get("remaining_amount"))

    return register_payable_payment(
        payable_id=payable_id,
        amount=amount,
        payment_date=form.get("date", date.today().isoformat()),
        account=form.get("account_id") or form.get("account") or item.get("account_id") or item.get("account", ""),
        account_id=form.get("account_id") or item.get("account_id") or form.get("account", ""),
        payment_method_id=form.get("payment_method_id") or item.get("preferred_payment_method_id", ""),
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
    account_id: str | None = None,
    payment_method_id: str | None = None,
) -> dict[str, Any]:
    item = payable_by_id(payable_id)
    if not item:
        return {"ok": False, "error": "Payable was not found."}

    requested_amount = _amount(amount)
    remaining_before = _amount(item.get("remaining_amount"))
    amount = min(requested_amount, remaining_before)
    if amount <= 0:
        return {"ok": False, "error": "Payable payment amount must be greater than zero."}

    effective_account_id = account_id or item.get("account_id") or account or item.get("account", "")
    effective_payment_method_id = payment_method_id or item.get("preferred_payment_method_id") or ""
    payment_account = account if account is not None else item.get("account", "")
    tx_payload = {
        "type": "expense",
        "date": payment_date or date.today().isoformat(),
        "category": item.get("category") or DEFAULT_PAYABLE_EXPENSE_CATEGORY,
        "sub_category": item.get("name", ""),
        "amount": amount,
        "account": payment_account or effective_account_id,
        "account_id": effective_account_id,
        "payment_method_id": effective_payment_method_id,
        "description": description or f"Payable payment to {item.get('payee', '')}: {item.get('name', '')}",
        "linked_object_type": "payable",
        "linked_object_id": str(item.get("id", payable_id)),
        "linked_object_name": item.get("name", ""),
    }
    if extra_tx_fields:
        tx_payload.update(dict(extra_tx_fields))

    save_result = save_transaction_payload(
        tx_payload,
        account_id=tx_payload.get("account_id"),
        payment_method_id=tx_payload.get("payment_method_id"),
        payment_method=payment_method,
        insufficient_action=insufficient_action,
    )
    if isinstance(save_result, dict) and not save_result.get("ok", True):
        return save_result
    transaction_ids = save_result.get("transaction_ids", []) if isinstance(save_result, dict) else []

    from money_manager.services.expense_project_service import attach_payable_payment_to_linked_projects

    for tx_id in transaction_ids:
        attach_payable_payment_to_linked_projects(
            payable_id=payable_id,
            transaction_id=tx_id,
            note=f"Payable payment: {item.get('name', '')}",
        )

    remaining = max(0.0, remaining_before - amount)
    updates = {
        "remaining_amount": remaining,
        "account": payment_account or effective_account_id,
        **snapshot_account(effective_account_id),
        "preferred_payment_method_id": effective_payment_method_id,
        "preferred_payment_method_name_snapshot": snapshot_payment_method(effective_payment_method_id)["payment_method_name_snapshot"],
    }
    if remaining <= 0.005:
        updates["status"] = "paid"
        updates["closed_at"] = datetime.now().isoformat(timespec="seconds")
    update_payable(int(item["id"]), updates)
    try:
        from money_manager.services.timeline_service import record_amount_change, record_payment, record_status_change

        tx_id = transaction_ids[0] if transaction_ids else ""
        record_payment(
            "payable",
            item.get("id", payable_id),
            amount,
            effective_account_id,
            "expense",
            tx_id,
            title=f"Paid €{amount:.2f} from {effective_account_id or 'selected account'}",
        )
        record_amount_change("payable", item.get("id", payable_id), "remaining_amount", remaining_before, remaining)
        if updates.get("status"):
            record_status_change("payable", item.get("id", payable_id), item.get("status", ""), updates.get("status", ""))
    except Exception:
        pass

    result = dict(save_result or {"ok": True})
    result.update({"ok": True, "paid_amount": amount, "remaining_amount": remaining, "payable_id": payable_id})
    return result


def payable_by_id(payable_id) -> dict | None:
    for row in load_payables():
        if str(row.get("id")) == str(payable_id):
            return row
    return None


def immediate_payable_reminders(*, limit: int = 6, today: date | None = None, scope=None) -> list[dict[str, Any]]:
    """Return the closest active payables for dashboard reminder cards.

    Unlike alert notifications, this intentionally includes every active payable
    with remaining money, even when it is not overdue or inside the notification
    window.  It is a passive reminder list for the home dashboard.
    """

    today = today or date.today()
    rows = load_payables()
    if scope is not None:
        try:
            rows = payable_rows_for_scope(rows, scope)
        except Exception:
            rows = []

    reminders: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("status", "active")).strip().lower() != "active":
            continue

        remaining = _amount(row.get("remaining_amount"))
        if remaining <= 0.005:
            continue

        due = _parse_payable_date(row.get("due_date"))
        start = _parse_payable_date(row.get("start_date"))
        created = _parse_payable_datetime_date(row.get("created_at"))
        sort_date = due or start or created or date.max
        due_label = _payable_due_label(due, today)
        tone = _payable_due_tone(due, today)

        reminders.append({
            "id": row.get("id", ""),
            "name": str(row.get("name") or "Payable"),
            "payee": str(row.get("payee") or "Unknown payee"),
            "category": str(row.get("category") or DEFAULT_PAYABLE_EXPENSE_CATEGORY),
            "description": str(row.get("description") or ""),
            "account_label": str(row.get("account_name_snapshot") or row.get("account") or row.get("account_id") or "No account"),
            "remaining_amount": float(remaining),
            "due_date": due.isoformat() if due else "",
            "due_label": due_label,
            "tone": tone,
            "sort_date": sort_date.isoformat() if sort_date != date.max else "",
            "_sort_key": (0 if due else 1, sort_date, str(row.get("name") or "").lower()),
        })

    reminders.sort(key=lambda item: item["_sort_key"])
    for item in reminders:
        item.pop("_sort_key", None)
    return reminders[:max(0, int(limit or 0))]


def overview_totals(scope=None) -> dict:
    rows = load_payables()
    scoped = scope is not None
    if scoped:
        rows = payable_rows_for_scope(rows, scope)
    active = [row for row in rows if row.get("status") == "active" and _amount(row.get("remaining_amount")) > 0]
    finished = [row for row in rows if row not in active]
    active_remaining = sum(_amount(row.get("remaining_amount")) for row in active)
    original_total = sum(_amount(row.get("original_amount")) for row in rows)
    paid_total = sum(max(0.0, _amount(row.get("original_amount")) - _amount(row.get("remaining_amount"))) for row in rows)
    # In account scope, every row has already been filtered to the selected Conto,
    # so the selected account's projected net must subtract the whole remaining amount.
    # In global/legacy scope, keep the older split for compatibility with existing reports.
    main_remaining = active_remaining if scoped else sum(_amount(row.get("remaining_amount")) for row in active if _payable_hits_main_net(row))
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


def page_context(main_net: float = 0.0, visible_liquidity: float = 0.0, scope=None) -> dict:
    rows = load_payables()
    selected_scope = scope or "global"
    if scope is not None:
        rows = payable_rows_for_scope(rows, selected_scope)
        try:
            from money_manager.services.account_scope_service import scope_balance_summary
            scoped_summary = scope_balance_summary(selected_scope)
            main_net = float(scoped_summary.get("net_balance", main_net) or 0.0)
            visible_liquidity = float(scoped_summary.get("net_balance", visible_liquidity) or 0.0)
        except Exception:
            pass
    for row in rows:
        original = _amount(row.get("original_amount"))
        linked_transactions = _linked_payable_transactions(row.get("id"))
        paid_from_transactions = sum(_amount(tx.get("amount")) for tx in linked_transactions)
        remaining = max(0.0, original - paid_from_transactions) if linked_transactions else _amount(row.get("remaining_amount"))
        row["original_amount"] = original
        row["remaining_amount"] = remaining
        row["paid_amount"] = paid_from_transactions if linked_transactions else max(0.0, original - remaining)
        row["linked_transaction_rows"] = linked_transactions
        try:
            from money_manager.services.payable_detail_service import details_for_payable
            row["details"] = details_for_payable(row.get("id"))
        except Exception:
            row["details"] = {"items": [], "files": [], "items_total": 0.0}
        row["progress"] = 0.0 if original <= 0 else min(100.0, row["paid_amount"] / original * 100.0)
        try:
            from money_manager.services.timeline_service import enrich_object_row

            enrich_object_row(row, "payable")
        except Exception:
            row.setdefault("timeline_text", "No timeline events yet.")
            row.setdefault("payment_history_text", "No payments recorded yet.")
            row.setdefault("linked_transactions_text", "No linked transactions yet.")

    active = [row for row in rows if row.get("status") == "active" and _amount(row.get("remaining_amount")) > 0]
    finished = [row for row in rows if row not in active]
    totals = overview_totals(selected_scope if scope is not None else None)
    totals["main_net_now"] = float(main_net)
    totals["visible_liquidity_now"] = float(visible_liquidity)
    totals["main_net_if_paid_all"] = float(main_net - totals["main_remaining"])
    totals["visible_liquidity_if_paid_all"] = float(visible_liquidity - totals["active_remaining"])
    selected_account_id = ""
    if scope is not None:
        try:
            from money_manager.services.account_scope_service import resolve_account_scope

            selected_account_id = str(resolve_account_scope(selected_scope).get("account_id") or "")
        except Exception:
            selected_account_id = ""
    form_ctx = payment_form_context("expense", selected_account_id=selected_account_id)

    return {
        "payables": rows,
        "active_payables": active,
        "finished_payables": finished,
        "totals": totals,
        "today": date.today().isoformat(),
        "selected_scope": selected_scope,
        "account_options": account_options_for_payment_forms(include_credit=True),
        **form_ctx,
    }


def _payable_hits_main_net(row: dict) -> bool:
    account_id = row.get("account_id") or row.get("account", "")
    return normalize_account_key(account_id) == MAIN_ACCOUNT_KEY


def _parse_payable_date(value) -> date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    for candidate in (raw[:10], raw):
        try:
            return date.fromisoformat(candidate)
        except ValueError:
            continue
    return None


def _parse_payable_datetime_date(value) -> date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw).date()
    except ValueError:
        return _parse_payable_date(raw)


def _payable_due_label(due: date | None, today: date) -> str:
    if due is None:
        return "No due date"
    delta = (due - today).days
    if delta < 0:
        days = abs(delta)
        return f"Overdue by {days} day{'s' if days != 1 else ''}"
    if delta == 0:
        return "Due today"
    if delta == 1:
        return "Due tomorrow"
    return f"Due in {delta} days"


def _payable_due_tone(due: date | None, today: date) -> str:
    if due is None:
        return "neutral"
    if due <= today:
        return "critical"
    if due <= today + timedelta(days=7):
        return "warning"
    return "info"


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


# --- Scoped payable compatibility wrappers (Prompt 15B) ---
def payable_rows_for_scope(rows: list[dict], scope, user_id: str | None = None) -> list[dict]:
    from money_manager.services.account_scope_service import payable_rows_for_scope as _scoped_rows

    return _scoped_rows(rows, scope, user_id=user_id)


def payables_total_for_scope(scope, user_id: str | None = None) -> float:
    from money_manager.services.account_scope_service import payables_total_for_scope as _scoped_total

    return float(_scoped_total(scope, user_id=user_id))


def payables_context_for_scope(scope, user_id: str | None = None) -> dict:
    from money_manager.services.account_scope_service import payables_context_for_scope as _scoped_context

    return _scoped_context(scope, user_id=user_id)
