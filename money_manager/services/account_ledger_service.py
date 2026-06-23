from __future__ import annotations

"""Account ledger service for the Prompt 11C accounting foundation.

The ledger is append/audit-oriented.  Existing transaction CSVs remain the v10
source for dashboards until later prompts migrate forms and calculations.

Sign convention:
- Asset accounts are positive balances.
- Cash/asset outflows are negative signed_amount values.
- Liability accounts are negative balances; a credit-card charge posts a
  negative movement to the liability account.
- Voiding never deletes history. It marks original rows voided and appends
  reversal rows with opposite signed_amount values.
"""

import csv
import json
import uuid
from dataclasses import asdict, is_dataclass
from datetime import date as date_cls, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from money_manager.config.user_paths import user_data_path
from money_manager.domain.constants import ACCOUNT_LEDGER_FIELDS
from money_manager.domain.payment import LedgerMovementDraft, PaymentResolution
from money_manager.repositories.account_ledger import ensure_account_ledger_file, read_ledger_rows, write_ledger_rows
from money_manager.repositories.csv_files import next_numeric_id
from money_manager.services.payment_routing_service import resolve_payment, resolution_json_dumps

POSTED_STATUSES = {"posted"}
ACTIVE_STATUSES_WITH_SCHEDULED = {"posted", "scheduled"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_account_ledger(user_id: str | None = None) -> Path:
    return ensure_account_ledger_file(user_id=user_id)


def load_ledger(include_void: bool = False, user_id: str | None = None) -> list[dict[str, Any]]:
    rows = read_ledger_rows(user_id=user_id)
    if include_void:
        return rows
    return [row for row in rows if not _truthy(row.get("is_void")) and str(row.get("status") or "") != "voided"]


def append_ledger_movements(movements: Iterable[Any], user_id: str | None = None) -> list[str]:
    """Append ledger movement rows and return their row ids.

    Each item can be a full ledger row dict, a LedgerMovementDraft, or a dict
    shaped like LedgerMovementDraft plus optional ledger metadata.  Missing ids,
    timestamps, currency, and status are filled conservatively.
    """
    path = ensure_account_ledger(user_id=user_id)
    existing = read_ledger_rows(user_id=user_id)
    next_id = next_numeric_id(existing, field="id")
    appended: list[dict[str, Any]] = []
    ids: list[str] = []
    for item in movements:
        raw = _movement_to_dict(item)
        row = _normalize_ledger_row(raw, next_id=next_id)
        next_id += 1
        appended.append(row)
        ids.append(str(row["id"]))
    if not appended:
        return []
    all_rows = [*existing, *appended]
    write_ledger_rows(all_rows, user_id=user_id)
    _notify_cache_changed()
    return ids


def ledger_rows_for_transaction(transaction_uid: str, include_void: bool = True, user_id: str | None = None) -> list[dict[str, Any]]:
    wanted = str(transaction_uid or "").strip()
    return [row for row in load_ledger(include_void=include_void, user_id=user_id) if str(row.get("transaction_uid") or "") == wanted]


def void_ledger_group(ledger_group_id: str, reason: str = "", user_id: str | None = None) -> dict[str, Any]:
    group_id = str(ledger_group_id or "").strip()
    if not group_id:
        return {"ok": False, "voided_rows": 0, "reversal_rows": 0, "error": "Missing ledger_group_id."}
    ensure_account_ledger(user_id=user_id)
    all_rows = read_ledger_rows(user_id=user_id)
    void_group = f"void_{uuid.uuid4().hex}"
    reversal_rows: list[dict[str, Any]] = []
    changed = 0
    next_id = next_numeric_id(all_rows, field="id")
    for row in all_rows:
        if str(row.get("ledger_group_id") or "") != group_id:
            continue
        if _truthy(row.get("is_void")) or str(row.get("status") or "") == "voided":
            continue
        row["status"] = "voided"
        row["voided_by_ledger_group_id"] = void_group
        changed += 1
        reversal = dict(row)
        reversal["id"] = str(next_id)
        next_id += 1
        reversal["ledger_group_id"] = void_group
        reversal["status"] = "voided"
        reversal["is_void"] = "1"
        reversal["voided_by_ledger_group_id"] = group_id
        reversal["signed_amount"] = _format_money(-_to_float(row.get("signed_amount")))
        reversal["direction"] = _reverse_direction(str(row.get("direction") or ""))
        reversal["movement_kind"] = f"void_{row.get('movement_kind') or 'movement'}"
        reversal["notes"] = f"Void reversal for {group_id}. {reason}".strip()
        reversal["created_at"] = utc_now()
        reversal["created_from_resolution_json"] = json.dumps({"void_reason": reason, "voids_ledger_group_id": group_id}, ensure_ascii=False)
        reversal_rows.append(_normalize_ledger_row(reversal, next_id=next_id))
    if changed:
        all_rows.extend(reversal_rows)
        write_ledger_rows(all_rows, user_id=user_id)
    return {"ok": True, "voided_rows": changed, "reversal_rows": len(reversal_rows), "void_ledger_group_id": void_group}


def void_ledger_for_transaction(transaction_uid: str, reason: str = "", user_id: str | None = None) -> dict[str, Any]:
    rows = ledger_rows_for_transaction(transaction_uid, include_void=False, user_id=user_id)
    groups = sorted({str(row.get("ledger_group_id") or "") for row in rows if row.get("ledger_group_id")})
    if not groups:
        return {"ok": True, "voided_rows": 0, "reversal_rows": 0, "groups": []}
    total_voided = 0
    total_reversal = 0
    reports = []
    for group_id in groups:
        report = void_ledger_group(group_id, reason=reason, user_id=user_id)
        reports.append(report)
        total_voided += int(report.get("voided_rows") or 0)
        total_reversal += int(report.get("reversal_rows") or 0)
    return {"ok": True, "voided_rows": total_voided, "reversal_rows": total_reversal, "groups": groups, "reports": reports}


def append_adjustment_rows_for_transaction(transaction_uid: str, reason: str = "", user_id: str | None = None) -> dict[str, Any]:
    """Append balancing adjustment rows for an already-settled transaction.

    Unlike void_ledger_for_transaction(), this keeps the original posted rows as
    historical facts and adds posted counter-movements. Use it for confirmed
    edits/deletes where silently rewriting settled credit history would be too
    destructive.
    """
    uid = str(transaction_uid or "").strip()
    if not uid:
        return {"ok": False, "adjustment_rows": 0, "error": "Missing transaction_uid."}
    rows = ledger_rows_for_transaction(uid, include_void=False, user_id=user_id)
    if not rows:
        return {"ok": True, "adjustment_rows": 0, "adjustment_ledger_group_id": ""}

    adjustment_group = f"adj_{uuid.uuid4().hex}"
    adjustment_rows: list[dict[str, Any]] = []
    for row in rows:
        adjustment = dict(row)
        adjustment["id"] = ""
        adjustment["ledger_group_id"] = adjustment_group
        adjustment["status"] = "posted"
        adjustment["is_void"] = "0"
        adjustment["voided_by_ledger_group_id"] = ""
        adjustment["signed_amount"] = _format_money(-_to_float(row.get("signed_amount")))
        adjustment["direction"] = _reverse_direction(str(row.get("direction") or ""))
        adjustment["movement_kind"] = f"adjustment_reverse_{row.get('movement_kind') or 'movement'}"
        adjustment["notes"] = f"Settlement-safe adjustment for {uid}. {reason}".strip()
        adjustment["created_at"] = utc_now()
        adjustment["created_from_resolution_json"] = json.dumps(
            {
                "adjustment_reason": reason,
                "adjusts_transaction_uid": uid,
                "adjusts_ledger_group_id": row.get("ledger_group_id", ""),
            },
            ensure_ascii=False,
        )
        adjustment_rows.append(adjustment)

    append_ledger_movements(adjustment_rows, user_id=user_id)
    return {"ok": True, "adjustment_rows": len(adjustment_rows), "adjustment_ledger_group_id": adjustment_group}


def account_balance_from_ledger(
    account_id: str,
    as_of: str | date_cls | datetime | None = None,
    include_scheduled: bool = False,
    user_id: str | None = None,
) -> float:
    wanted = str(account_id or "").strip()
    if not wanted:
        return 0.0
    statuses = ACTIVE_STATUSES_WITH_SCHEDULED if include_scheduled else POSTED_STATUSES
    total = 0.0
    for row in load_ledger(include_void=False, user_id=user_id):
        if str(row.get("account_id") or "") != wanted:
            continue
        if str(row.get("status") or "posted") not in statuses:
            continue
        if as_of is not None and _date_after(row.get("effective_date") or row.get("date"), as_of):
            continue
        total += _to_float(row.get("signed_amount"))
    return round(total, 2)


def account_balances_from_ledger(
    as_of: str | date_cls | datetime | None = None,
    include_scheduled: bool = False,
    user_id: str | None = None,
) -> dict[str, float]:
    balances: dict[str, float] = {}
    statuses = ACTIVE_STATUSES_WITH_SCHEDULED if include_scheduled else POSTED_STATUSES
    for row in load_ledger(include_void=False, user_id=user_id):
        status = str(row.get("status") or "posted")
        if status not in statuses:
            continue
        if as_of is not None and _date_after(row.get("effective_date") or row.get("date"), as_of):
            continue
        account_id = str(row.get("account_id") or "")
        if not account_id:
            continue
        balances[account_id] = round(balances.get(account_id, 0.0) + _to_float(row.get("signed_amount")), 2)
    return balances


def scheduled_movements(as_of: str | date_cls | datetime | None = None, user_id: str | None = None) -> list[dict[str, Any]]:
    rows = [row for row in load_ledger(include_void=False, user_id=user_id) if str(row.get("status") or "") == "scheduled"]
    if as_of is None:
        return rows
    return [row for row in rows if not _date_after(row.get("effective_date") or row.get("date"), as_of)]


def validate_ledger_rows(user_id: str | None = None) -> dict[str, Any]:
    rows = read_ledger_rows(user_id=user_id)
    errors: list[dict[str, Any]] = []
    ids: set[str] = set()
    for index, row in enumerate(rows, start=2):
        row_errors: list[str] = []
        row_id = str(row.get("id") or "")
        if not row_id:
            row_errors.append("missing_id")
        elif row_id in ids:
            row_errors.append("duplicate_id")
        ids.add(row_id)
        for field in ["ledger_group_id", "date", "effective_date", "account_id", "movement_kind", "direction", "amount", "signed_amount", "status"]:
            if str(row.get(field) or "") == "":
                row_errors.append(f"missing_{field}")
        if str(row.get("status") or "") not in {"posted", "scheduled", "voided", "simulated"}:
            row_errors.append("invalid_status")
        if _to_float(row.get("amount")) < 0:
            row_errors.append("amount_must_be_positive")
        try:
            json_text = str(row.get("created_from_resolution_json") or "").strip()
            if json_text:
                json.loads(json_text)
        except json.JSONDecodeError:
            row_errors.append("invalid_created_from_resolution_json")
        if row_errors:
            errors.append({"line": index, "id": row_id, "errors": row_errors})
    return {"ok": not errors, "row_count": len(rows), "error_count": len(errors), "errors": errors}


def rebuild_ledger_from_transactions(dry_run: bool = True, user_id: str | None = None) -> dict[str, Any]:
    """Infer ledger rows from existing transaction CSVs.

    This is an opt-in repair/preview helper.  It tolerates old rows with missing
    payment_method/account snapshots and does not change legacy dashboard math.
    """
    from money_manager.repositories.transactions import load_by_type

    inferred: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    existing_uids = {str(row.get("transaction_uid") or "") for row in load_ledger(include_void=True, user_id=user_id)}
    for tx_type in ("expense", "income", "investment"):
        try:
            df = load_by_type(tx_type)
        except Exception as exc:
            skipped.append({"transaction_type": tx_type, "id": "", "reason": f"load_failed: {exc}"})
            continue
        if df.empty:
            continue
        for _, row in df.fillna("").iterrows():
            row_dict = {key: row.get(key, "") for key in df.columns}
            tx_id = str(row_dict.get("id") or "").strip()
            if not tx_id:
                skipped.append({"transaction_type": tx_type, "id": "", "reason": "missing_id"})
                continue
            uid = f"{tx_type}:{tx_id}"
            if uid in existing_uids:
                skipped.append({"transaction_type": tx_type, "id": tx_id, "reason": "ledger_exists"})
                continue
            try:
                resolution = resolve_payment(
                    tx_type,
                    _to_float(row_dict.get("amount")),
                    row_dict.get("date") or date_cls.today().isoformat(),
                    account_id=row_dict.get("account_key_snapshot") or row_dict.get("account") or None,
                    payment_method_id=row_dict.get("payment_method") or None,
                    category=row_dict.get("category"),
                    sub_category=row_dict.get("sub_category"),
                    description=row_dict.get("description") or "",
                    existing_row=row_dict,
                    user_id=user_id,
                )
            except Exception as exc:
                skipped.append({"transaction_type": tx_type, "id": tx_id, "reason": f"resolve_failed: {exc}"})
                continue
            if not resolution.ok:
                skipped.append({"transaction_type": tx_type, "id": tx_id, "reason": "; ".join(resolution.errors)})
                continue
            rows = rows_from_payment_resolution(
                resolution,
                transaction_uid=uid,
                transaction_type=tx_type,
                transaction_id=tx_id,
                source_kind="rebuild_preview" if dry_run else "rebuild",
                source_id=tx_id,
            )
            inferred.extend(rows)
    if not dry_run and inferred:
        append_ledger_movements(inferred, user_id=user_id)
    return {
        "ok": True,
        "dry_run": dry_run,
        "inferred_movement_count": len(inferred),
        "skipped_count": len(skipped),
        "skipped": skipped[:200],
        "movements": inferred if dry_run else [],
    }


def rows_from_payment_resolution(
    resolution: PaymentResolution,
    *,
    transaction_uid: str = "",
    transaction_type: str = "",
    transaction_id: str = "",
    source_kind: str = "payment_resolution",
    source_id: str = "",
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    resolution_json = resolution_json_dumps(resolution)
    for movement in resolution.movements:
        raw = movement.to_dict() if isinstance(movement, LedgerMovementDraft) else dict(movement)
        raw.update({
            "ledger_group_id": resolution.ledger_group_id,
            "transaction_uid": transaction_uid,
            "transaction_type": transaction_type or resolution.transaction_type,
            "transaction_id": transaction_id,
            "source_kind": source_kind,
            "source_id": source_id,
            "date": resolution.transaction_date,
            "payment_method_id": resolution.payment_method_id,
            "payment_method_name_snapshot": resolution.payment_method_name_snapshot,
            "currency": resolution.currency or "EUR",
            "created_from_resolution_json": resolution_json,
        })
        rows.append(raw)
    return rows


def _normalize_ledger_row(raw: Mapping[str, Any], *, next_id: int) -> dict[str, str]:
    row = {field: "" for field in ACCOUNT_LEDGER_FIELDS}
    for field in ACCOUNT_LEDGER_FIELDS:
        value = raw.get(field, "")
        if value is None:
            value = ""
        row[field] = str(value)
    row["id"] = row["id"] or str(next_id)
    row["ledger_group_id"] = row["ledger_group_id"] or f"lg_{uuid.uuid4().hex}"
    row["date"] = row["date"] or row.get("effective_date") or date_cls.today().isoformat()
    row["effective_date"] = row["effective_date"] or row["date"]
    row["amount"] = _format_money(abs(_to_float(row.get("amount"))))
    row["signed_amount"] = _format_money(_to_float(row.get("signed_amount")))
    if row["signed_amount"] == "0.00" and _to_float(row["amount"]):
        sign = -1 if str(row.get("direction") or "").lower() in {"out", "liability_increase"} else 1
        row["signed_amount"] = _format_money(sign * _to_float(row["amount"]))
    row["currency"] = (row["currency"] or "EUR").upper()
    row["status"] = row["status"] or "posted"
    row["is_void"] = "1" if _truthy(row.get("is_void")) else "0"
    row["created_at"] = row["created_at"] or utc_now()
    return row


def _movement_to_dict(item: Any) -> dict[str, Any]:
    if isinstance(item, LedgerMovementDraft):
        return item.to_dict()
    if is_dataclass(item):
        return asdict(item)
    if isinstance(item, Mapping):
        return dict(item)
    raise TypeError(f"Unsupported ledger movement type: {type(item).__name__}")


def _headers(path: Path) -> list[str]:
    rows = read_ledger_rows()
    return list(rows[0].keys()) if rows else ACCOUNT_LEDGER_FIELDS


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


def _reverse_direction(direction: str) -> str:
    mapping = {
        "in": "void_in",
        "out": "void_out",
        "liability_increase": "liability_decrease",
        "liability_decrease": "liability_increase",
    }
    return mapping.get(direction, f"void_{direction}" if direction else "void")


def _to_float(value: Any) -> float:
    try:
        return float(str(value or "0").replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def _format_money(value: float) -> str:
    return f"{round(float(value or 0.0), 2):.2f}"


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _notify_cache_changed() -> None:
    try:
        from money_manager.services.cache_service import notify_data_changed
        notify_data_changed()
    except Exception:
        pass
