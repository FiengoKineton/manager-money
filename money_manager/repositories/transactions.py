from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from money_manager.config import (
    MAIN_ACCOUNT_KEY,
    MAIN_NET_CREDIT_PENDING,
    TRANSACTION_FILES,
    TRANSACTION_TYPES,
    account_due_day_for_key,
    account_label_for_key,
    account_policy_for_key,
)
from money_manager.domain.constants import TRANSACTION_FIELDS
from money_manager.config.user_paths import get_user_data_dir, using_user
from money_manager.security.secure_storage import read_json_secure
from money_manager.domain.transaction import make_transaction_uid, parse_transaction_uid
from money_manager.repositories.yearly_partitioned import (
    YearlyDatasetSpec,
    append_partitioned_row,
    ensure_partitioned,
    load_summary,
    mutate_partitioned_row,
    next_partitioned_id,
    read_partitioned_rows,
)
from money_manager.services.account_service import enrich_transactions_with_accounts, _affects_main_net_mask, _valid_dated_transactions


NEW_PAYMENT_COLUMNS = [
    "transaction_uid",
    "account_id",
    "payment_method_id",
    "payment_method_name_snapshot",
    "payment_channel_method_id_snapshot",
    "payment_channel_name_snapshot",
    "funding_account_id_snapshot",
    "funding_account_name_snapshot",
    "settlement_account_id_snapshot",
    "settlement_account_name_snapshot",
    "liability_account_id_snapshot",
    "liability_account_name_snapshot",
    "settlement_mode_snapshot",
    "payment_due_date_snapshot",
    "payment_due_day_snapshot",
    "payment_statement_period_snapshot",
    "payment_resolution_json",
    "ledger_group_id",
    "ledger_status",
]


def _transaction_signed_value(transaction_type: str):
    def signed(row: Mapping[str, Any]) -> float:
        try:
            amount = float(str(row.get("amount") or "0").replace(",", "."))
        except (TypeError, ValueError):
            amount = 0.0
        if transaction_type == "income":
            return amount
        if transaction_type == "expense":
            return -amount
        return amount if str(row.get("category") or "").casefold() == "dividend" else -amount
    return signed


def _routing_context_fingerprint(user_id: str | None = None) -> str:
    """Fingerprint configuration that can change historical account routing."""
    user_dir = get_user_data_dir(user_id)
    payload: dict[str, Any] = {"summary_logic_version": 1}
    for filename in ("accounts.json", "payment_methods.json", "categories.json"):
        payload[filename] = read_json_secure(user_dir / filename, default={}, user_id=user_id)
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:24]


def _transaction_account_totals(transaction_type: str):
    """Build exact per-account contributions in one vectorized enrichment pass."""
    def totals(rows: list[Mapping[str, Any]], user_id: str | None = None) -> Mapping[str, float]:
        if not rows:
            return {}
        context = using_user(user_id) if user_id else nullcontext()
        with context:
            frame = pd.DataFrame([dict(row) for row in rows])
            frame["type"] = transaction_type
            frame["amount"] = pd.to_numeric(frame.get("amount", 0.0), errors="coerce").fillna(0.0)
            frame["signed_amount"] = _signed_amount_series(frame)
            enriched = enrich_transactions_with_accounts(frame)
            result: dict[str, float] = {}

            # Main can receive a contribution even when a row is also routed to a
            # dependent wallet (for example a legacy top-up category). Reuse the
            # application's existing routing rule so the summary matches the UI.
            valid = _valid_dated_transactions(enriched)
            main_rows = valid[_affects_main_net_mask(valid)].copy() if not valid.empty else valid
            if not main_rows.empty:
                result[MAIN_ACCOUNT_KEY] = float(pd.to_numeric(main_rows.get("signed_amount", 0.0), errors="coerce").fillna(0.0).sum())

            if "account_key" in enriched.columns:
                non_main = enriched[enriched["account_key"].fillna("").astype(str) != MAIN_ACCOUNT_KEY].copy()
                if not non_main.empty:
                    values = pd.to_numeric(non_main.get("account_signed_amount", 0.0), errors="coerce").fillna(0.0)
                    grouped = values.groupby(non_main["account_key"].fillna("").astype(str)).sum()
                    for key, value in grouped.items():
                        if key:
                            result[str(key)] = result.get(str(key), 0.0) + float(value)
            return result
    return totals


def _transaction_account_counts(transaction_type: str):
    """Count rows affecting each account using the same routing model as balances."""
    def counts(rows: list[Mapping[str, Any]], user_id: str | None = None) -> Mapping[str, int]:
        if not rows:
            return {}
        context = using_user(user_id) if user_id else nullcontext()
        with context:
            frame = pd.DataFrame([dict(row) for row in rows])
            frame["type"] = transaction_type
            frame["amount"] = pd.to_numeric(frame.get("amount", 0.0), errors="coerce").fillna(0.0)
            frame["signed_amount"] = _signed_amount_series(frame)
            enriched = enrich_transactions_with_accounts(frame)
            result: dict[str, int] = {}
            valid = _valid_dated_transactions(enriched)
            main_rows = valid[_affects_main_net_mask(valid)] if not valid.empty else valid
            if not main_rows.empty:
                result[MAIN_ACCOUNT_KEY] = int(len(main_rows))
            if "account_key" in enriched.columns:
                non_main = enriched[enriched["account_key"].fillna("").astype(str) != MAIN_ACCOUNT_KEY]
                if not non_main.empty:
                    grouped = non_main.groupby(non_main["account_key"].fillna("").astype(str)).size()
                    for key, value in grouped.items():
                        if key:
                            result[str(key)] = result.get(str(key), 0) + int(value)
            return result
    return counts


_TRANSACTION_SPECS = {
    tx_type: YearlyDatasetSpec(
        name=f"{tx_type}s" if tx_type != "expense" else "expenses",
        legacy_filename={"expense": "expenses.csv", "income": "incomes.csv", "investment": "investments.csv"}[tx_type],
        folder_name={"expense": "expenses", "income": "incomes", "investment": "investments"}[tx_type],
        file_prefix={"expense": "expenses", "income": "incomes", "investment": "investments"}[tx_type],
        fields=tuple(TRANSACTION_FIELDS),
        signed_value=_transaction_signed_value(tx_type),
        account_totals_for_rows=_transaction_account_totals(tx_type),
        account_counts_for_rows=_transaction_account_counts(tx_type),
        context_fingerprint=_routing_context_fingerprint,
    )
    for tx_type in TRANSACTION_TYPES
}


def partition_spec_for_type(transaction_type: str) -> YearlyDatasetSpec:
    try:
        return _TRANSACTION_SPECS[str(transaction_type)]
    except KeyError as exc:
        raise ValueError(f"Unknown transaction type: {transaction_type}") from exc


def _notify_cache_changed() -> None:
    try:
        from money_manager.services.cache_service import notify_data_changed

        notify_data_changed()
    except Exception:
        pass


def csv_path_for_type(transaction_type: str) -> Path:
    try:
        return TRANSACTION_FILES[transaction_type]
    except KeyError as exc:
        raise ValueError(f"Unknown transaction type: {transaction_type}") from exc


def load_by_type(
    transaction_type: str,
    *,
    start: Any = None,
    end: Any = None,
    years: list[int] | None = None,
    user_id: str | None = None,
) -> pd.DataFrame:
    spec = partition_spec_for_type(transaction_type)
    rows = read_partitioned_rows(spec, start=start, end=end, years=years, user_id=user_id)
    if not rows:
        return pd.DataFrame(columns=TRANSACTION_FIELDS)
    return pd.DataFrame(rows, columns=TRANSACTION_FIELDS).fillna("")


def load_all(*, start: Any = None, end: Any = None, years: list[int] | None = None, user_id: str | None = None) -> pd.DataFrame:
    """Load transaction partitions, optionally touching only intersecting years."""
    frames = []

    for transaction_type in TRANSACTION_TYPES:
        df = load_by_type(transaction_type, start=start, end=end, years=years, user_id=user_id)
        if not df.empty:
            df["type"] = transaction_type
            frames.append(df)

    if not frames:
        return pd.DataFrame(columns=[*TRANSACTION_FIELDS, "type", "signed_amount"])

    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    df["signed_amount"] = _signed_amount_series(df)
    df = enrich_transactions_with_accounts(df)
    df = df.sort_values(by=["date", "created_at"], ascending=[False, False])
    return df



def _signed_amount_series(df: pd.DataFrame) -> pd.Series:
    """Vectorized equivalent of _signed_amount for the hot transaction loader."""
    if df.empty:
        return pd.Series(dtype=float, index=df.index)

    amount = pd.to_numeric(df.get("amount", 0.0), errors="coerce").fillna(0.0)
    transaction_type = df.get("type", pd.Series("", index=df.index)).fillna("").astype(str).str.casefold()
    category = df.get("category", pd.Series("", index=df.index)).fillna("").astype(str).str.casefold()

    signed = pd.Series(0.0, index=df.index, dtype=float)
    signed.loc[transaction_type.eq("income")] = amount.loc[transaction_type.eq("income")]
    signed.loc[transaction_type.eq("expense")] = -amount.loc[transaction_type.eq("expense")]
    investment = transaction_type.eq("investment")
    dividend = investment & category.eq("dividend")
    signed.loc[dividend] = amount.loc[dividend]
    signed.loc[investment & ~dividend] = -amount.loc[investment & ~dividend]
    return signed

def _credit_account_snapshot_for_row(row: dict) -> dict[str, str]:
    """Return stable credit-account metadata to store with newly-created rows.

    The enriched account columns are still computed at runtime for old CSV
    compatibility. These snapshot columns are only used to keep credit statement
    due dates stable after the user later changes a credit account's due day.
    """
    try:
        probe = pd.DataFrame([{**row, "type": row.get("type", "expense"), "signed_amount": _signed_amount(row)}])
        enriched = enrich_transactions_with_accounts(probe)
        account_key = str(enriched.iloc[0].get("account_key", "") or "")
    except Exception:
        account_key = ""

    if not account_key or account_policy_for_key(account_key) != MAIN_NET_CREDIT_PENDING:
        return {
            "account_key_snapshot": "",
            "account_name_snapshot": row.get("account_name_snapshot", "") or "",
            "account_due_day_snapshot": "",
        }

    return {
        "account_key_snapshot": account_key,
        "account_name_snapshot": account_label_for_key(account_key),
        "account_due_day_snapshot": str(account_due_day_for_key(account_key, 15)),
    }


def append_transaction(tx: dict) -> int:
    """Append a transaction row without doing service-level payment side effects.

    Prompt 11D keeps repositories simple: callers that want ledger rows resolve
    payment in transaction_service.py first, then pass the resulting snapshots in
    ``tx``. Legacy callers can still pass only the old v10 keys.
    """
    transaction_type = str(tx.get("type") or "")
    spec = partition_spec_for_type(transaction_type)
    row_id = next_partitioned_id(spec)
    now = datetime.now().isoformat(timespec="seconds")
    row = {field: "" for field in TRANSACTION_FIELDS}
    row.update({field: _clean_cell(tx.get(field, "")) for field in TRANSACTION_FIELDS if field in tx})
    row.update(
        {
            "id": str(row_id),
            "transaction_uid": tx.get("transaction_uid") or make_transaction_uid(str(transaction_type), row_id),
            "date": tx.get("date", ""),
            "category": tx.get("category", ""),
            "sub_category": tx.get("sub_category", ""),
            # amount is always stored in EUR. Foreign-currency inputs keep their
            # original amount/rate in the columns below and in the description.
            "amount": str(tx.get("amount", "0")),
            "original_amount": tx.get("original_amount", ""),
            "original_currency": tx.get("original_currency", ""),
            "exchange_rate_to_eur": tx.get("exchange_rate_to_eur", ""),
            "exchange_correction_to_eur": tx.get("exchange_correction_to_eur", ""),
            "exchange_effective_rate_to_eur": tx.get("exchange_effective_rate_to_eur", ""),
            "account": tx.get("account", ""),
            "account_id": tx.get("account_id", ""),
            "account_key_snapshot": tx.get("account_key_snapshot", ""),
            "account_name_snapshot": tx.get("account_name_snapshot", ""),
            "account_due_day_snapshot": tx.get("account_due_day_snapshot", ""),
            "payment_method": tx.get("payment_method", ""),
            "payment_method_id": tx.get("payment_method_id", ""),
            "contact_id": tx.get("contact_id", ""),
            "contact_name": tx.get("contact_name", ""),
            "iban_snapshot": tx.get("iban_snapshot", ""),
            "bic_swift_snapshot": tx.get("bic_swift_snapshot", ""),
            "bank_name_snapshot": tx.get("bank_name_snapshot", ""),
            "transfer_reference": tx.get("transfer_reference", ""),
            "transfer_status": tx.get("transfer_status", ""),
            "description": tx.get("description", ""),
            "created_at": tx.get("created_at") or now,
        }
    )

    if not row["account_due_day_snapshot"]:
        credit_snapshot = _credit_account_snapshot_for_row({**row, "type": transaction_type})
        # Do not overwrite richer Prompt 11D snapshots except for the legacy
        # account-key/due-day columns that this helper owns.
        row["account_key_snapshot"] = row.get("account_key_snapshot") or credit_snapshot.get("account_key_snapshot", "")
        row["account_name_snapshot"] = row.get("account_name_snapshot") or credit_snapshot.get("account_name_snapshot", "")
        row["account_due_day_snapshot"] = credit_snapshot.get("account_due_day_snapshot", "")

    append_partitioned_row(spec, row)
    return int(row_id)


def update_transaction(tx_id: int | str, transaction_type: str, data: dict) -> bool:
    spec = partition_spec_for_type(transaction_type)
    editable = {field: _clean_cell(value) for field, value in data.items() if field in TRANSACTION_FIELDS and field != "id"}
    changed = mutate_partitioned_row(
        spec,
        lambda row: str(row.get("id")) == str(tx_id),
        update=editable,
    )
    if changed:
        _notify_cache_changed()
    return changed


def delete_transaction(tx_id: int | str, transaction_type: str) -> bool:
    spec = partition_spec_for_type(transaction_type)
    changed = mutate_partitioned_row(
        spec,
        lambda row: str(row.get("id")) == str(tx_id),
        delete=True,
    )
    if changed:
        _notify_cache_changed()
    return changed


def transaction_partition_summaries(user_id: str | None = None) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for tx_type, spec in _TRANSACTION_SPECS.items():
        ensure_partitioned(spec, user_id=user_id)
        result[tx_type] = load_summary(spec, user_id=user_id)
    return result


def transaction_available_years(user_id: str | None = None) -> list[int]:
    years: set[int] = set()
    for summary in transaction_partition_summaries(user_id=user_id).values():
        years.update(int(value) for value in summary.get("available_years", []) if str(value).isdigit())
    return sorted(years)


def transaction_summary_totals(user_id: str | None = None) -> dict[str, float]:
    summaries = transaction_partition_summaries(user_id=user_id)
    income = float(summaries.get("income", {}).get("signed_total") or 0.0)
    expense_signed = float(summaries.get("expense", {}).get("signed_total") or 0.0)
    investment_signed = float(summaries.get("investment", {}).get("signed_total") or 0.0)
    net = income + expense_signed + investment_signed
    return {
        "income": income,
        "expenses": abs(expense_signed),
        "investments": abs(investment_signed),
        "net": net,
        "savings_rate": max(net, 0.0) / income * 100.0 if income > 1e-9 else 0.0,
        "total_availability": net + abs(investment_signed),
    }


def transaction_account_summary_totals(user_id: str | None = None) -> dict[str, float]:
    """Return all-time transaction contributions without rereading old rows."""
    totals: dict[str, float] = {}
    for summary in transaction_partition_summaries(user_id=user_id).values():
        for key, value in (summary.get("totals_by_account") or {}).items():
            totals[str(key)] = totals.get(str(key), 0.0) + float(value or 0.0)
    return totals


def get_transaction_by_uid(transaction_uid: str) -> dict[str, Any] | None:
    parsed = parse_transaction_uid(transaction_uid)
    if not parsed:
        return None
    try:
        df = load_by_type(parsed.transaction_type)
    except ValueError:
        return None
    if df.empty:
        return None
    if "transaction_uid" not in df.columns:
        df["transaction_uid"] = ""
    uid_mask = df["transaction_uid"].fillna("").astype(str) == transaction_uid
    id_mask = df["id"].fillna("").astype(str) == parsed.tx_id
    match = df[uid_mask | id_mask]
    if match.empty:
        return None
    row = match.iloc[0].fillna("").to_dict()
    row["type"] = parsed.transaction_type
    if not row.get("transaction_uid"):
        row["transaction_uid"] = make_transaction_uid(parsed.transaction_type, row.get("id", parsed.tx_id))
    return row


def update_transaction_by_uid(transaction_uid: str, data: dict) -> bool:
    parsed = parse_transaction_uid(transaction_uid)
    if not parsed:
        return False
    return update_transaction(parsed.tx_id, parsed.transaction_type, data)


def transaction_row_to_payment_context(row: Mapping[str, Any]) -> dict[str, Any]:
    tx_type = str(row.get("type") or row.get("transaction_type") or "").casefold()
    tx_id = str(row.get("id") or row.get("transaction_id") or "")
    uid = str(row.get("transaction_uid") or make_transaction_uid(tx_type, tx_id))
    return {
        "transaction_uid": uid,
        "transaction_type": tx_type,
        "transaction_id": tx_id,
        "date": _clean_cell(row.get("date", "")),
        "amount": _to_float(row.get("amount")),
        "category": _clean_cell(row.get("category", "")),
        "sub_category": _clean_cell(row.get("sub_category", "")),
        "description": _clean_cell(row.get("description", "")),
        "account": _clean_cell(row.get("account", "")),
        "account_id": _first_nonblank(
            row.get("account_id"),
            row.get("account_key_snapshot"),
            row.get("account"),
        ),
        "payment_method": _clean_cell(row.get("payment_method", "")),
        "payment_method_id": _first_nonblank(row.get("payment_method_id"), row.get("payment_method")),
        "ledger_group_id": _clean_cell(row.get("ledger_group_id", "")),
    }


def transaction_has_payment_snapshots(row: Mapping[str, Any]) -> bool:
    return any(str(row.get(field) or "").strip() for field in NEW_PAYMENT_COLUMNS)


def transaction_is_legacy_payment(row: Mapping[str, Any]) -> bool:
    return not transaction_has_payment_snapshots(row)


def _signed_amount(row) -> float:
    transaction_type = row.get("type")
    amount = float(row.get("amount", 0.0))
    category = str(row.get("category", "")).lower()

    if transaction_type == "income":
        return amount
    if transaction_type == "expense":
        return -amount
    if transaction_type == "investment":
        return amount if category == "dividend" else -amount
    return 0.0


def _clean_cell(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    return "" if text.casefold() in {"nan", "nat", "none", "null"} else text


def _first_nonblank(*values: Any) -> str:
    for value in values:
        text = _clean_cell(value).strip()
        if text:
            return text
    return ""


def _to_float(value: Any) -> float:
    try:
        return float(str(value or "0").replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def transaction_account_summary_counts(user_id: str | None = None) -> dict[str, int]:
    """Return indexed all-time transaction row counts by affected account."""
    counts: dict[str, int] = {}
    for summary in transaction_partition_summaries(user_id=user_id).values():
        for key, value in (summary.get("row_counts_by_account") or {}).items():
            counts[str(key)] = counts.get(str(key), 0) + int(value or 0)
    return counts
