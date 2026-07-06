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
from money_manager.config import CREDIT_CARD_PAYMENT_CATEGORY
from money_manager.repositories.credit_settlements import (
    append_settlement,
    find_by_id,
    load_rows,
    update_settlement,
    upsert_by_uid,
)
from money_manager.repositories.pending import load_pending, write_pending, mark_executed
from money_manager.repositories.transactions import append_transaction, load_all as load_transactions
from money_manager.services.account_config_service import account_by_key, account_label_for_key
from money_manager.services.account_ledger_service import append_ledger_movements, load_ledger
from money_manager.services.payment_method_service import payment_method_by_id
from money_manager.services.payment_routing_service import compute_due_date, compute_statement_period

CREDIT_SETTLEMENT_SOURCE = "credit_settlement"
CREDIT_SETTLEMENT_KIND = "credit_settlement"
EXECUTABLE_STATUSES = {"open", "scheduled"}
FINAL_STATUSES = {"executed", "cancelled", "adjusted", "superseded"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _backfill_missing_credit_liability_movements(user_id: str | None = None) -> int:
    """Create missing credit-liability ledger rows from delayed transaction snapshots.

    Older saves/edits could store the transaction's delayed payment snapshots but
    fail to append the matching `credit_liability_increase` ledger row.  The
    settlement window is ledger-backed, so those purchases looked invisible even
    though the transaction detail correctly said it was paid by credit card.

    The backfill is conservative: it only touches expense rows that already carry
    delayed/credit snapshots and skips every transaction UID that already has an
    active credit-liability movement.
    """
    try:
        from money_manager.domain.transaction import make_transaction_uid
        from money_manager.repositories.transactions import load_all as load_transactions
        from money_manager.services.payment_routing_service import compute_statement_period
    except Exception:
        return 0

    existing_credit_uids = {
        str(row.get("transaction_uid") or "")
        for row in load_ledger(include_void=False, user_id=user_id)
        if str(row.get("movement_kind") or "") == "credit_liability_increase"
    }
    try:
        df = load_transactions()
    except Exception:
        return 0
    if df.empty:
        return 0

    rows_to_append: list[dict[str, Any]] = []
    for _, tx in df.fillna("").iterrows():
        tx_row = tx.to_dict()
        tx_type = _clean_snapshot_value(tx_row.get("type")).casefold()
        if tx_type != "expense":
            continue
        settlement_mode = _clean_snapshot_value(tx_row.get("settlement_mode_snapshot")).casefold()
        due_date = _clean_snapshot_value(tx_row.get("payment_due_date_snapshot"))
        liability_id = _clean_snapshot_value(tx_row.get("liability_account_id_snapshot"))
        if settlement_mode != "delayed" and not (due_date and liability_id):
            continue
        amount = abs(_to_float(tx_row.get("amount")))
        if amount <= 0.005:
            continue

        tx_uid = _clean_snapshot_value(tx_row.get("transaction_uid")) or make_transaction_uid(tx_type, _clean_snapshot_value(tx_row.get("id")))
        if not tx_uid or tx_uid in existing_credit_uids:
            continue

        liability_id = liability_id or "credit_card"
        settlement_id = (
            _clean_snapshot_value(tx_row.get("settlement_account_id_snapshot"))
            or _clean_snapshot_value(tx_row.get("funding_account_id_snapshot"))
            or "main_bank"
        )
        method_id = (
            _clean_snapshot_value(tx_row.get("payment_channel_method_id_snapshot"))
            or _clean_snapshot_value(tx_row.get("payment_method_id"))
        )
        method_name = (
            _clean_snapshot_value(tx_row.get("payment_channel_name_snapshot"))
            or _clean_snapshot_value(tx_row.get("payment_method_name_snapshot"))
            or method_id
        )
        tx_date = _clean_snapshot_value(tx_row.get("date"))[:10] or date_cls.today().isoformat()
        statement_period = _clean_snapshot_value(tx_row.get("payment_statement_period_snapshot")) or compute_statement_period(tx_date)
        if not due_date:
            due_day = int(_to_float(tx_row.get("payment_due_day_snapshot")) or 15)
            from money_manager.services.payment_routing_service import compute_due_date

            due_date = compute_due_date(tx_date, due_day=due_day)

        ledger_group_id = _clean_snapshot_value(tx_row.get("ledger_group_id")) or f"lg_credit_backfill_{uuid.uuid4().hex}"
        metadata = {
            "payment_method_id": method_id,
            "payment_method_name_snapshot": method_name,
            "settlement_mode": "delayed",
            "funding_account_id": _clean_snapshot_value(tx_row.get("funding_account_id_snapshot")) or settlement_id,
            "settlement_account_id": settlement_id,
            "liability_account_id": liability_id,
            "due_date": due_date,
            "due_day_snapshot": _clean_snapshot_value(tx_row.get("payment_due_day_snapshot")),
            "statement_period": statement_period,
            "movement_count": 1,
            "backfilled_from_transaction_snapshot": True,
        }
        rows_to_append.append({
            "ledger_group_id": ledger_group_id,
            "transaction_uid": tx_uid,
            "transaction_type": tx_type,
            "transaction_id": _clean_snapshot_value(tx_row.get("id")),
            "source_kind": "transaction_credit_backfill",
            "source_id": _clean_snapshot_value(tx_row.get("id")),
            "date": tx_date,
            "effective_date": tx_date,
            "account_id": liability_id,
            "account_name_snapshot": _clean_snapshot_value(tx_row.get("liability_account_name_snapshot")) or account_label_for_key(liability_id, user_id=user_id),
            "payment_method_id": method_id,
            "payment_method_name_snapshot": method_name,
            "movement_kind": "credit_liability_increase",
            "direction": "liability_increase",
            "amount": amount,
            "currency": "EUR",
            "signed_amount": -amount,
            "status": "posted",
            "is_void": "0",
            "created_from_resolution_json": json.dumps(metadata, ensure_ascii=False, sort_keys=True),
            "notes": "Backfilled credit-card liability movement from delayed transaction snapshot.",
        })
        existing_credit_uids.add(tx_uid)

    if rows_to_append:
        append_ledger_movements(rows_to_append, user_id=user_id)
    return len(rows_to_append)


def _clean_snapshot_value(value: Any) -> str:
    text = str(value or "").strip()
    if text.lower() in {"nan", "nat", "none", "null"}:
        return ""
    return text




def _transaction_lookup_for_credit_settlements() -> dict[str, dict[str, Any]]:
    """Return current transaction rows keyed by their stable transaction UID.

    Credit settlements must follow the current transaction route, not stale
    ledger rows left behind by earlier edits.  If an expense was changed from a
    credit/deferred route back to PayPal balance, its old credit-liability ledger
    row should not keep generating a statement settlement.
    """
    try:
        from money_manager.domain.transaction import make_transaction_uid

        df = load_transactions()
    except Exception:
        return {}
    lookup: dict[str, dict[str, Any]] = {}
    if df.empty:
        return lookup
    for _, tx in df.fillna("").iterrows():
        row = tx.to_dict()
        tx_uid = _clean_snapshot_value(row.get("transaction_uid"))
        if not tx_uid:
            tx_uid = make_transaction_uid(_clean_snapshot_value(row.get("type")), _clean_snapshot_value(row.get("id")))
        if tx_uid:
            lookup[tx_uid] = row
    return lookup


def _transaction_row_is_active_credit_purchase(row: Mapping[str, Any]) -> bool:
    tx_type = _clean_snapshot_value(row.get("type")).casefold()
    if tx_type != "expense":
        return False
    settlement_mode = _clean_snapshot_value(row.get("settlement_mode_snapshot")).casefold()
    due_date = _clean_snapshot_value(row.get("payment_due_date_snapshot"))
    liability_id = _clean_snapshot_value(row.get("liability_account_id_snapshot"))
    category = _clean_snapshot_value(row.get("category")).casefold()
    sub_category = _clean_snapshot_value(row.get("sub_category")).casefold()
    description = _clean_snapshot_value(row.get("description")).casefold()
    text = f"{category} {sub_category} {description}"
    if "settlement" in text or "statement payment" in text or "credit card payment" in text:
        return False
    return settlement_mode == "delayed" or bool(due_date and liability_id)


def _ledger_row_matches_current_credit_purchase(row: Mapping[str, Any], transaction_lookup: Mapping[str, Mapping[str, Any]]) -> bool:
    """Ignore stale credit-liability rows whose transaction was later edited.

    The ledger is the durable settlement source, but in this app transactions can
    still be edited from a credit route back to an immediate route.  During that
    transition older files may keep a posted credit-liability row.  Cross-check
    the current transaction CSV so those stale rows do not inflate the statement
    amount from €200 to €400.
    """
    tx_uid = _clean_snapshot_value(row.get("transaction_uid"))
    if not tx_uid:
        return True
    tx_row = transaction_lookup.get(tx_uid)
    if tx_row is None:
        source_kind = _clean_snapshot_value(row.get("source_kind")).casefold()
        return not source_kind.startswith("transaction")
    if not _transaction_row_is_active_credit_purchase(tx_row):
        return False
    tx_ledger_group = _clean_snapshot_value(tx_row.get("ledger_group_id"))
    row_ledger_group = _clean_snapshot_value(row.get("ledger_group_id"))
    if tx_ledger_group and row_ledger_group and tx_ledger_group != row_ledger_group:
        return False
    return True

def _credit_rule_method(payment_method_id: str, user_id: str | None = None) -> dict[str, Any] | None:
    """Return the real credit-card method that owns statement rules.

    A visible wrapper such as PayPal via Credit Card is the checkout channel, but
    the due day and liability account belong to its delegated credit card.
    """
    method = payment_method_by_id(payment_method_id, include_archived=True, user_id=user_id) if payment_method_id else None
    if not method:
        return None
    if str(method.get("settlement_mode") or "") == "delegated":
        delegate_id = str(method.get("delegates_to_payment_method_id") or "").strip()
        delegate = payment_method_by_id(delegate_id, include_archived=True, user_id=user_id) if delegate_id else None
        if delegate and (str(delegate.get("method_type") or "") == "credit_card" or str(delegate.get("settlement_mode") or "") == "delayed"):
            return delegate
    return method


def _safe_day(value: Any, default: int = 15) -> int:
    try:
        day = int(float(str(value or "").strip()))
    except (TypeError, ValueError):
        day = default
    return max(1, min(31, day))


def _effective_credit_schedule(row: Mapping[str, Any], metadata: Mapping[str, Any], user_id: str | None = None) -> dict[str, str]:
    """Recompute the statement month/due date from the purchase date.

    Older rows sometimes carried a same-month due-date snapshot after wrapper
    repair.  Credit-card purchases should be grouped by their actual charge
    month and settled on the configured day of the following month, unless the
    method explicitly says otherwise.
    """
    tx_date = (
        _clean_snapshot_value(row.get("effective_date"))
        or _clean_snapshot_value(row.get("date"))
        or _clean_snapshot_value(metadata.get("transaction_date"))
        or date_cls.today().isoformat()
    )[:10]
    payment_method_id = _clean_snapshot_value(row.get("payment_method_id")) or _clean_snapshot_value(metadata.get("payment_method_id"))
    method = _credit_rule_method(payment_method_id, user_id=user_id) or {}
    rules = method.get("rules") if isinstance(method.get("rules"), Mapping) else {}

    due_day = _safe_day(
        rules.get("due_day")
        or metadata.get("due_day_snapshot")
        or metadata.get("due_day")
        or row.get("payment_due_day_snapshot"),
        15,
    )
    statement_day_raw = rules.get("statement_day")
    try:
        statement_day = int(statement_day_raw) if statement_day_raw else None
    except (TypeError, ValueError):
        statement_day = None
    policy = str(rules.get("settlement_day_policy") or metadata.get("settlement_day_policy") or "next_month").strip() or "next_month"

    statement_period = compute_statement_period(tx_date, statement_day=statement_day)
    due_date = compute_due_date(tx_date, due_day=due_day, statement_day=statement_day, policy=policy)
    return {
        "due_date": due_date,
        "statement_period": statement_period,
        "due_day": str(due_day),
        "statement_day": str(statement_day or ""),
        "settlement_day_policy": policy,
    }


def group_unsettled_credit_movements(user_id: str | None = None) -> list[dict[str, Any]]:
    settled_groups = _settled_ledger_group_ids(user_id=user_id)
    transaction_lookup = _transaction_lookup_for_credit_settlements()
    groups: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    for row in load_ledger(include_void=False, user_id=user_id):
        if str(row.get("movement_kind") or "") != "credit_liability_increase":
            continue
        if str(row.get("status") or "posted") not in {"posted", "scheduled"}:
            continue
        ledger_group_id = str(row.get("ledger_group_id") or "")
        if ledger_group_id in settled_groups:
            continue
        if not _ledger_row_matches_current_credit_purchase(row, transaction_lookup):
            continue
        metadata = _resolution_metadata(row)
        schedule = _effective_credit_schedule(row, metadata, user_id=user_id)
        due_date = schedule["due_date"]
        statement_period = schedule["statement_period"]
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
                "due_day_snapshot": schedule.get("due_day", ""),
                "settlement_day_policy": schedule.get("settlement_day_policy", "next_month"),
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
    _backfill_missing_credit_liability_movements(user_id=user_id)
    _repair_missing_executed_settlement_transactions(user_id=user_id)
    created_or_updated: list[int] = []
    current_uids: set[str] = set()
    for group in group_unsettled_credit_movements(user_id=user_id):
        if _to_float(group.get("amount")) <= 0.005:
            continue
        current_uids.add(str(group.get("settlement_uid") or ""))
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
    superseded = _supersede_stale_open_settlements(current_uids, sync_pending=sync_pending)
    return {"ok": True, "settlement_count": len(created_or_updated), "settlement_ids": created_or_updated, "superseded_count": superseded}


def _supersede_stale_open_settlements(current_uids: set[str], *, sync_pending: bool = True) -> int:
    changed = 0
    for row in load_rows():
        status = str(row.get("status") or "open").lower()
        if status in FINAL_STATUSES:
            continue
        uid = str(row.get("settlement_uid") or "")
        if uid in current_uids:
            continue
        update_settlement(row.get("id", ""), {
            "status": "superseded",
            "notes": _merge_note(row.get("notes"), "Superseded by recalculated credit-card statement schedule."),
            "updated_at": utc_now(),
        })
        if sync_pending:
            _cancel_pending_for_settlement(row.get("id", ""))
        changed += 1
    return changed


def _merge_note(existing: Any, note: str) -> str:
    text = str(existing or "").strip()
    note = str(note or "").strip()
    if not note or note in text:
        return text
    return f"{text} | {note}" if text else note


def _repair_missing_executed_settlement_transactions(user_id: str | None = None) -> int:
    repaired = 0
    for row in load_rows():
        if str(row.get("status") or "").lower() != "executed":
            continue
        tx_uid = str(row.get("executed_transaction_uid") or f"credit_settlement:{row.get('id')}")
        if _transaction_uid_exists(tx_uid):
            continue
        _append_settlement_transaction(row, _date_to_str(row.get("due_date")) or date_cls.today().isoformat(), user_id=user_id, automatic=False)
        repaired += 1
    return repaired


def _transaction_uid_exists(tx_uid: str) -> bool:
    wanted = str(tx_uid or "").strip()
    if not wanted:
        return False
    try:
        df = load_transactions()
    except Exception:
        return False
    if df.empty or "transaction_uid" not in df.columns:
        return False
    return bool(df["transaction_uid"].fillna("").astype(str).eq(wanted).any())


def _settlement_purchase_date_label(row: Mapping[str, Any], user_id: str | None = None) -> str:
    groups = set(str(item) for item in _json_list(row.get("created_from_ledger_group_ids_json")) if item)
    if not groups:
        return ""
    dates: list[str] = []
    for ledger in load_ledger(include_void=False, user_id=user_id):
        if str(ledger.get("ledger_group_id") or "") not in groups:
            continue
        if str(ledger.get("movement_kind") or "") != "credit_liability_increase":
            continue
        day = _date_to_str(ledger.get("effective_date") or ledger.get("date"))
        if day:
            dates.append(day)
    dates = sorted(set(dates))
    if not dates:
        return ""
    if len(dates) == 1:
        return f"purchase made on {dates[0]}"
    return f"purchases from {dates[0]} to {dates[-1]}"


def _auto_description(description: str, automatic: bool) -> str:
    text = str(description or "").strip()
    if not automatic:
        return text
    if "auto" in text.casefold():
        return text
    return f"{text} [auto]" if text else "Credit-card settlement [auto]"


def _append_settlement_transaction(row: Mapping[str, Any], effective: str, *, user_id: str | None = None, automatic: bool = False) -> int:
    tx_uid = str(row.get("executed_transaction_uid") or f"credit_settlement:{row.get('id')}")
    if _transaction_uid_exists(tx_uid):
        return 0
    amount = _to_float(row.get("amount"))
    settlement_account_id = str(row.get("settlement_account_id") or "main_bank")
    statement = str(row.get("statement_period") or "").strip()
    method_name = str(row.get("payment_method_name_snapshot") or row.get("liability_account_name_snapshot") or "Credit card").strip()
    purchase_label = _settlement_purchase_date_label(row, user_id=user_id)
    description_parts = [
        f"{method_name} settlement",
        f"statement {statement}" if statement else "",
        purchase_label,
        f"paid on {effective}" if effective else "",
    ]
    description = _auto_description("; ".join(part for part in description_parts if part), automatic)
    return append_transaction({
        "type": "expense",
        "transaction_uid": tx_uid,
        "date": effective,
        "category": CREDIT_CARD_PAYMENT_CATEGORY,
        "sub_category": method_name,
        "amount": f"{amount:.2f}",
        "account": settlement_account_id,
        "account_id": settlement_account_id,
        "account_key_snapshot": settlement_account_id,
        "account_name_snapshot": row.get("settlement_account_name_snapshot") or account_label_for_key(settlement_account_id, user_id=user_id),
        "payment_method": row.get("payment_method_name_snapshot") or "",
        "payment_method_id": row.get("payment_method_id") or "",
        "payment_method_name_snapshot": row.get("payment_method_name_snapshot") or "",
        "payment_channel_method_id_snapshot": row.get("payment_method_id") or "",
        "payment_channel_name_snapshot": row.get("payment_method_name_snapshot") or "",
        "settlement_mode_snapshot": "immediate",
        "payment_statement_period_snapshot": statement,
        "ledger_group_id": row.get("ledger_group_id") or "",
        "ledger_status": "posted",
        "description": description,
    })


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


def execute_credit_settlement(
    settlement_id: str | int,
    execution_date: str | date_cls | datetime | None = None,
    user_id: str | None = None,
    *,
    automatic: bool = False,
) -> dict[str, Any]:
    row = find_by_id(settlement_id)
    if not row:
        return {"ok": False, "error": "Credit settlement not found."}
    status = str(row.get("status") or "open").lower()
    if status == "executed":
        effective_existing = _date_to_str(execution_date) or _date_to_str(row.get("due_date")) or date_cls.today().isoformat()
        tx_id = _append_settlement_transaction(row, effective_existing, user_id=user_id, automatic=automatic)
        return {"ok": True, "already_executed": True, "ledger_group_id": row.get("ledger_group_id", ""), "transaction_id": tx_id}
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
    tx_id = _append_settlement_transaction({**row, "ledger_group_id": ledger_group_id, "executed_transaction_uid": tx_uid}, effective, user_id=user_id, automatic=automatic)
    update_settlement(row.get("id", ""), {
        "status": "executed",
        "ledger_group_id": ledger_group_id,
        "executed_transaction_uid": tx_uid,
        "executed_transaction_id": str(tx_id or ""),
        "executed_at": utc_now(),
        "updated_at": utc_now(),
    })
    _mark_pending_for_settlement(row.get("id", ""))
    return {"ok": True, "ledger_ids": ledger_ids, "ledger_group_id": ledger_group_id, "executed_transaction_uid": tx_uid, "transaction_id": tx_id}


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
            executed.append(execute_credit_settlement(row.get("id", ""), execution_date=target, user_id=user_id, automatic=True))
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
