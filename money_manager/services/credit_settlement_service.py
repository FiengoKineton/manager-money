from __future__ import annotations

"""Credit-card statement settlement layer.

This service keeps the old Pending page compatible while adding durable
credit_settlements.csv rows and real ledger movements. Credit purchases remain
ordinary transaction/ledger rows; this layer groups the unresolved credit
liability movements into statement settlements and executes each settlement once.
"""

import json
import uuid
from datetime import date as date_cls, datetime, timezone
from typing import Any, Mapping

from money_manager.domain.payment import LedgerMovementDraft
from money_manager.repositories.credit_settlements import (
    append_settlement,
    find_by_id,
    load_rows,
    update_settlement,
    upsert_by_uid,
)
from money_manager.repositories.pending import load_pending, write_pending, mark_executed
from money_manager.services.account_config_service import account_by_key, account_label_for_key
from money_manager.services.account_ledger_service import append_ledger_movements, load_ledger
from money_manager.services.payment_method_service import payment_method_by_id

CREDIT_SETTLEMENT_SOURCE = "credit_settlement"
CREDIT_SETTLEMENT_KIND = "credit_settlement"
EXECUTABLE_STATUSES = {"open", "scheduled"}
FINAL_STATUSES = {"executed", "cancelled", "adjusted"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def group_unsettled_credit_movements(user_id: str | None = None) -> list[dict[str, Any]]:
    settled_groups = _settled_ledger_group_ids(user_id=user_id)
    groups: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    for row in load_ledger(include_void=False, user_id=user_id):
        if str(row.get("movement_kind") or "") != "credit_liability_increase":
            continue
        if str(row.get("status") or "posted") not in {"posted", "scheduled"}:
            continue
        ledger_group_id = str(row.get("ledger_group_id") or "")
        if ledger_group_id in settled_groups:
            continue
        metadata = _resolution_metadata(row)
        due_date = str(metadata.get("due_date") or "")
        statement_period = str(metadata.get("statement_period") or "")
        liability_account_id = str(row.get("account_id") or metadata.get("liability_account_id") or "credit_card")
        settlement_account_id = str(metadata.get("settlement_account_id") or metadata.get("funding_account_id") or "main_bank")
        payment_method_id = str(row.get("payment_method_id") or metadata.get("payment_method_id") or "")
        key = (payment_method_id, liability_account_id, settlement_account_id, due_date, statement_period)
        amount = abs(_to_float(row.get("signed_amount")))
        if key not in groups:
            payment_method = payment_method_by_id(payment_method_id, include_archived=True, user_id=user_id) if payment_method_id else None
            settlement_account = account_by_key(settlement_account_id, user_id=user_id, include_archived=True) or {}
            liability_account = account_by_key(liability_account_id, user_id=user_id, include_archived=True) or {}
            groups[key] = {
                "payment_method_id": payment_method_id,
                "payment_method_name_snapshot": (payment_method or {}).get("name", ""),
                "liability_account_id": liability_account_id,
                "liability_account_name_snapshot": liability_account.get("label") or liability_account.get("name") or row.get("account_name_snapshot") or liability_account_id,
                "settlement_account_id": settlement_account_id,
                "settlement_account_name_snapshot": settlement_account.get("label") or settlement_account.get("name") or settlement_account_id,
                "due_date": due_date,
                "statement_period": statement_period,
                "currency": row.get("currency") or "EUR",
                "amount": 0.0,
                "total_amount": 0.0,
                "movement_count": 0,
                "movement_ids": [],
                "ledger_group_ids": [],
                "transaction_uids": [],
            }
        group = groups[key]
        group["amount"] = group["total_amount"] = round(float(group["total_amount"]) + amount, 2)
        group["movement_count"] = int(group["movement_count"]) + 1
        group["movement_ids"].append(str(row.get("id") or ""))
        group["ledger_group_ids"].append(ledger_group_id)
        if row.get("transaction_uid"):
            group["transaction_uids"].append(str(row.get("transaction_uid") or ""))
    result: list[dict[str, Any]] = []
    for group in groups.values():
        group["ledger_group_ids"] = sorted({gid for gid in group["ledger_group_ids"] if gid})
        group["transaction_uids"] = sorted({uid for uid in group["transaction_uids"] if uid})
        group["settlement_uid"] = _settlement_uid_for_group(group)
        result.append(group)
    return sorted(result, key=lambda item: (item.get("due_date") or "9999-12-31", item.get("statement_period") or "", item.get("liability_account_id") or ""))


def sync_credit_settlements(today: date_cls | None = None, user_id: str | None = None, *, sync_pending: bool = True) -> dict[str, Any]:
    created_or_updated: list[int] = []
    for group in group_unsettled_credit_movements(user_id=user_id):
        if _to_float(group.get("amount")) <= 0.005:
            continue
        status = "scheduled" if _parse_date(group.get("due_date")) and _parse_date(group.get("due_date")) > (today or date_cls.today()) else "open"
        payload = {
            **group,
            "status": status,
            "amount": _money(group.get("amount")),
            "created_from_ledger_group_ids_json": json.dumps(group.get("ledger_group_ids", []), ensure_ascii=False),
            "notes": explain_credit_settlement_group(group),
        }
        settlement_id = upsert_by_uid(group["settlement_uid"], payload)
        created_or_updated.append(settlement_id)
        if sync_pending:
            _sync_pending_for_settlement_id(settlement_id)
    return {"ok": True, "settlement_count": len(created_or_updated), "settlement_ids": created_or_updated}


def preview_credit_settlements(as_of: str | date_cls | datetime | None = None, user_id: str | None = None) -> list[dict[str, Any]]:
    sync_credit_settlements(user_id=user_id, sync_pending=True)
    previews: list[dict[str, Any]] = []
    for row in load_rows():
        if str(row.get("status") or "open") in FINAL_STATUSES:
            continue
        if as_of is not None and _date_after(row.get("due_date"), as_of):
            continue
        amount = _to_float(row.get("amount"))
        previews.append({
            **row,
            "amount_value": amount,
            "amount_str": f"€ {amount:.2f}",
            "preview_movements": _settlement_ledger_drafts(row, status="scheduled"),
        })
    return sorted(previews, key=lambda item: (item.get("due_date") or "9999-12-31", item.get("payment_method_name_snapshot") or ""))


def execute_credit_settlement(settlement_id: str | int, execution_date: str | date_cls | datetime | None = None, user_id: str | None = None) -> dict[str, Any]:
    row = find_by_id(settlement_id)
    if not row:
        return {"ok": False, "error": "Credit settlement not found."}
    status = str(row.get("status") or "open").lower()
    if status == "executed":
        return {"ok": True, "already_executed": True, "ledger_group_id": row.get("ledger_group_id", "")}
    if status not in EXECUTABLE_STATUSES:
        return {"ok": False, "error": f"Settlement status '{status}' cannot be executed."}

    amount = _to_float(row.get("amount"))
    if amount <= 0:
        return {"ok": False, "error": "Settlement amount must be greater than zero."}
    effective = _date_to_str(execution_date) or str(row.get("due_date") or date_cls.today().isoformat())
    ledger_group_id = str(row.get("ledger_group_id") or f"cs_{uuid.uuid4().hex}")
    tx_uid = str(row.get("executed_transaction_uid") or f"credit_settlement:{row.get('id')}")
    movements = _settlement_ledger_drafts(row, status="posted", effective_date=effective, ledger_group_id=ledger_group_id, transaction_uid=tx_uid)
    ledger_ids = append_ledger_movements(movements, user_id=user_id)
    update_settlement(row.get("id", ""), {
        "status": "executed",
        "ledger_group_id": ledger_group_id,
        "executed_transaction_uid": tx_uid,
        "executed_at": utc_now(),
        "updated_at": utc_now(),
    })
    _mark_pending_for_settlement(row.get("id", ""))
    return {"ok": True, "ledger_ids": ledger_ids, "ledger_group_id": ledger_group_id, "executed_transaction_uid": tx_uid}


def settle_all_due(today: str | date_cls | datetime | None = None, user_id: str | None = None) -> dict[str, Any]:
    target = _parse_date(today) or date_cls.today()
    sync_credit_settlements(today=target, user_id=user_id, sync_pending=True)
    executed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for row in load_rows():
        if str(row.get("status") or "open") not in EXECUTABLE_STATUSES:
            continue
        due = _parse_date(row.get("due_date"))
        if due and due <= target:
            executed.append(execute_credit_settlement(row.get("id", ""), execution_date=target, user_id=user_id))
        else:
            skipped.append({"id": row.get("id"), "due_date": row.get("due_date")})
    return {"ok": True, "executed_count": len([item for item in executed if item.get("ok")]), "executed": executed, "skipped": skipped}


def settle_now_for_payment_method(payment_method_id: str, user_id: str | None = None) -> dict[str, Any]:
    sync_credit_settlements(user_id=user_id, sync_pending=True)
    wanted = str(payment_method_id or "").strip()
    results = []
    for row in load_rows():
        if str(row.get("payment_method_id") or "") != wanted:
            continue
        if str(row.get("status") or "open") in EXECUTABLE_STATUSES:
            results.append(execute_credit_settlement(row.get("id", ""), user_id=user_id))
    return {"ok": True, "executed_count": len([item for item in results if item.get("ok")]), "results": results}


def cancel_or_adjust_settlement(settlement_id: str | int, *, status: str = "cancelled", notes: str = "", amount: float | None = None) -> dict[str, Any]:
    row = find_by_id(settlement_id)
    if not row:
        return {"ok": False, "error": "Credit settlement not found."}
    current = str(row.get("status") or "open").lower()
    if current == "executed":
        return {"ok": False, "error": "Executed settlements cannot be cancelled. Add an adjustment instead."}
    status = status if status in {"cancelled", "adjusted", "open", "scheduled"} else "cancelled"
    updates: dict[str, Any] = {"status": status, "notes": notes or row.get("notes", ""), "updated_at": utc_now()}
    if amount is not None:
        updates["amount"] = _money(amount)
    update_settlement(settlement_id, updates)
    if status == "cancelled":
        _cancel_pending_for_settlement(settlement_id)
    else:
        _sync_pending_for_settlement_id(settlement_id)
    return {"ok": True, "status": status}


def discard_credit_settlement(settlement_id: str | int, *, notes: str = "") -> dict[str, Any]:
    """Skip one credit settlement without creating any ledger transaction.

    This is used by the Pending page discard action. It closes the durable
    credit_settlements.csv row so it disappears from the Credit settlement
    section, while keeping the mirrored pending row as ``discarded`` history so
    the same statement occurrence is not recreated on the next page load.
    """
    row = find_by_id(settlement_id)
    if not row:
        return {"ok": False, "error": "Credit settlement not found."}
    current = str(row.get("status") or "open").lower()
    if current == "executed":
        return {"ok": False, "error": "Executed settlements cannot be discarded."}

    existing_notes = str(row.get("notes") or "").strip()
    discard_note = notes or "Skipped from Pending page without creating a transaction."
    merged_notes = existing_notes
    if discard_note and discard_note not in existing_notes:
        merged_notes = f"{existing_notes} | {discard_note}" if existing_notes else discard_note

    update_settlement(settlement_id, {
        "status": "cancelled",
        "notes": merged_notes,
        "updated_at": utc_now(),
    })
    _mark_pending_discarded_for_settlement(settlement_id, pending_id=row.get("pending_id", ""))
    return {"ok": True, "status": "cancelled"}


def discard_credit_settlement_for_pending(pending_id: str | int) -> dict[str, Any]:
    """Discard a mirrored credit-settlement pending row and close its settlement.

    Returns ``handled=False`` when the pending row is not a credit-settlement
    mirror, allowing callers to fall back to the normal pending discard logic.
    """
    wanted = str(pending_id or "").strip()
    if not wanted:
        return {"ok": False, "handled": False, "error": "Missing pending id."}
    for pending in load_pending():
        if str(pending.get("id") or "") != wanted:
            continue
        if pending.get("source") != CREDIT_SETTLEMENT_SOURCE or not pending.get("source_id"):
            return {"ok": False, "handled": False}
        result = discard_credit_settlement(pending.get("source_id", ""))
        result["handled"] = True
        return result
    return {"ok": False, "handled": False, "error": "Pending row not found."}


def _mark_pending_discarded_for_settlement(settlement_id: str | int, *, pending_id: str | int | None = None) -> None:
    rows = load_pending()
    changed = False
    wanted_pending_id = str(pending_id or "").strip()
    for pending in rows:
        same_pending_id = wanted_pending_id and str(pending.get("id") or "") == wanted_pending_id
        same_source = pending.get("source") == CREDIT_SETTLEMENT_SOURCE and str(pending.get("source_id") or "") == str(settlement_id)
        if same_pending_id or same_source:
            pending["status"] = "discarded"
            changed = True
    if changed:
        write_pending(rows)


def settlement_rows_for_payment_method(payment_method_id: str) -> list[dict[str, Any]]:
    wanted = str(payment_method_id or "").strip()
    return [row for row in load_rows() if str(row.get("payment_method_id") or "") == wanted]


def settlement_rows_for_account(account_id: str) -> list[dict[str, Any]]:
    wanted = str(account_id or "").strip()
    return [
        row for row in load_rows()
        if str(row.get("liability_account_id") or "") == wanted or str(row.get("settlement_account_id") or "") == wanted
    ]


def settlement_due_dates(user_id: str | None = None) -> list[str]:
    sync_credit_settlements(user_id=user_id, sync_pending=True)
    return sorted({str(row.get("due_date") or "") for row in load_rows() if row.get("due_date") and str(row.get("status") or "") in EXECUTABLE_STATUSES})


def explain_credit_settlement_group(group: Mapping[str, Any]) -> str:
    amount = _to_float(group.get("amount") or group.get("total_amount"))
    period = group.get("statement_period") or "unknown statement"
    due = group.get("due_date") or "unknown due date"
    count = int(group.get("movement_count") or 0)
    liability = group.get("liability_account_name_snapshot") or group.get("liability_account_id") or "credit account"
    return f"Settle € {amount:.2f} for {liability}, statement {period}, due {due}, from {count} credit movement(s)."


def _sync_pending_for_settlement_id(settlement_id: str | int) -> str:
    row = find_by_id(settlement_id)
    if not row or str(row.get("status") or "open") in FINAL_STATUSES:
        return ""
    rows = load_pending()
    existing = next((item for item in rows if item.get("source") == CREDIT_SETTLEMENT_SOURCE and str(item.get("source_id")) == str(settlement_id)), None)
    payload = {
        "type": "expense",
        "date_due": row.get("due_date", ""),
        "amount": _money(row.get("amount")),
        "category": "Credit settlement",
        "account": row.get("settlement_account_id", ""),
        "description": row.get("notes") or f"{row.get('payment_method_name_snapshot') or row.get('liability_account_name_snapshot')} statement {row.get('statement_period')}",
        "status": "pending",
        "source": CREDIT_SETTLEMENT_SOURCE,
        "source_id": str(settlement_id),
        "pending_kind": CREDIT_SETTLEMENT_KIND,
        "account_key": row.get("settlement_account_id", ""),
        "account_label": row.get("settlement_account_name_snapshot", ""),
        "statement_month": row.get("statement_period", ""),
    }
    if existing:
        if str(existing.get("status") or "pending") == "pending":
            existing.update(payload)
            pending_id = str(existing.get("id") or "")
        else:
            pending_id = str(existing.get("id") or "")
    else:
        pending_id = str(_next_pending_id(rows))
        payload["id"] = pending_id
        rows.append(payload)
    write_pending(rows)
    update_settlement(settlement_id, {"pending_id": pending_id})
    return pending_id


def _mark_pending_for_settlement(settlement_id: str | int) -> None:
    row = find_by_id(settlement_id)
    pending_id = str((row or {}).get("pending_id") or "")
    if pending_id:
        try:
            mark_executed(int(pending_id))
            return
        except (TypeError, ValueError):
            pass
    rows = load_pending()
    changed = False
    for pending in rows:
        if pending.get("source") == CREDIT_SETTLEMENT_SOURCE and str(pending.get("source_id")) == str(settlement_id):
            pending["status"] = "executed"
            changed = True
    if changed:
        write_pending(rows)


def _cancel_pending_for_settlement(settlement_id: str | int) -> None:
    rows = load_pending()
    changed = False
    for pending in rows:
        if pending.get("source") == CREDIT_SETTLEMENT_SOURCE and str(pending.get("source_id")) == str(settlement_id) and pending.get("status") == "pending":
            pending["status"] = "cancelled"
            changed = True
    if changed:
        write_pending(rows)


def _settlement_ledger_drafts(row: Mapping[str, Any], *, status: str = "posted", effective_date: str | None = None, ledger_group_id: str | None = None, transaction_uid: str | None = None) -> list[dict[str, Any]]:
    amount = _to_float(row.get("amount"))
    effective = effective_date or str(row.get("due_date") or date_cls.today().isoformat())
    group_id = ledger_group_id or str(row.get("ledger_group_id") or f"cs_{uuid.uuid4().hex}")
    tx_uid = transaction_uid or str(row.get("executed_transaction_uid") or f"credit_settlement:{row.get('id', '')}")
    resolution_json = json.dumps({
        "settlement_uid": row.get("settlement_uid", ""),
        "payment_method_id": row.get("payment_method_id", ""),
        "created_from_ledger_group_ids": _json_list(row.get("created_from_ledger_group_ids_json")),
        "statement_period": row.get("statement_period", ""),
    }, ensure_ascii=False)
    settlement_account_id = str(row.get("settlement_account_id") or "main_bank")
    liability_account_id = str(row.get("liability_account_id") or "credit_card")
    base = {
        "ledger_group_id": group_id,
        "transaction_uid": tx_uid,
        "transaction_type": "credit_settlement",
        "transaction_id": str(row.get("id") or ""),
        "source_kind": CREDIT_SETTLEMENT_SOURCE,
        "source_id": str(row.get("id") or ""),
        "date": effective,
        "effective_date": effective,
        "payment_method_id": row.get("payment_method_id", ""),
        "payment_method_name_snapshot": row.get("payment_method_name_snapshot", ""),
        "currency": row.get("currency") or "EUR",
        "status": status,
        "created_from_resolution_json": resolution_json,
        "notes": row.get("notes") or "Credit card settlement",
    }
    return [
        {
            **base,
            "account_id": settlement_account_id,
            "account_name_snapshot": row.get("settlement_account_name_snapshot") or account_label_for_key(settlement_account_id),
            "counterparty_account_id": liability_account_id,
            "counterparty_account_name_snapshot": row.get("liability_account_name_snapshot") or account_label_for_key(liability_account_id),
            "movement_kind": "credit_settlement_cash_out",
            "direction": "out",
            "amount": amount,
            "signed_amount": -amount,
        },
        {
            **base,
            "account_id": liability_account_id,
            "account_name_snapshot": row.get("liability_account_name_snapshot") or account_label_for_key(liability_account_id),
            "counterparty_account_id": settlement_account_id,
            "counterparty_account_name_snapshot": row.get("settlement_account_name_snapshot") or account_label_for_key(settlement_account_id),
            "movement_kind": "credit_liability_decrease",
            "direction": "liability_decrease",
            "amount": amount,
            "signed_amount": amount,
        },
    ]


def _settled_ledger_group_ids(user_id: str | None = None) -> set[str]:
    result: set[str] = set()
    for row in load_rows():
        if str(row.get("status") or "").lower() not in {"executed", "cancelled", "adjusted"}:
            continue
        for group_id in _json_list(row.get("created_from_ledger_group_ids_json")):
            if group_id:
                result.add(str(group_id))
    return result


def _settlement_uid_for_group(group: Mapping[str, Any]) -> str:
    parts = [
        group.get("payment_method_id") or "method",
        group.get("liability_account_id") or "liability",
        group.get("settlement_account_id") or "settlement",
        group.get("statement_period") or "period",
        group.get("due_date") or "due",
    ]
    safe = "__".join(str(part).replace("/", "-").replace(" ", "_") for part in parts)
    return f"cs:{safe}"


def _resolution_metadata(row: Mapping[str, Any]) -> dict[str, Any]:
    text = str(row.get("created_from_resolution_json") or "").strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    text = str(value or "").strip()
    if not text:
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    return payload if isinstance(payload, list) else []


def _date_after(left: Any, right: Any) -> bool:
    left_date = _parse_date(left)
    right_date = _parse_date(right)
    if left_date is None or right_date is None:
        return False
    return left_date > right_date


def _parse_date(value: Any) -> date_cls | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date_cls):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        try:
            return date_cls.fromisoformat(text[:10])
        except ValueError:
            return None


def _date_to_str(value: Any) -> str:
    parsed = _parse_date(value)
    return parsed.isoformat() if parsed else ""


def _to_float(value: Any) -> float:
    try:
        return float(str(value or "0").replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def _money(value: Any) -> str:
    return f"{round(_to_float(value), 2):.2f}"


def _next_pending_id(rows: list[dict]) -> int:
    ids = [int(row.get("id", 0)) for row in rows if str(row.get("id", "")).isdigit()]
    return max(ids, default=0) + 1
