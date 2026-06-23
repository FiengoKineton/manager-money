from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from money_manager.config import (
    MAIN_NET_CREDIT_PENDING,
    TRANSACTION_FILES,
    TRANSACTION_TYPES,
    account_due_day_for_key,
    account_label_for_key,
    account_policy_for_key,
)
from money_manager.domain.constants import TRANSACTION_FIELDS
from money_manager.domain.transaction import make_transaction_uid, parse_transaction_uid
from money_manager.repositories.csv_files import append_row, ensure_csv, next_numeric_id, read_rows, write_rows
from money_manager.services.account_service import enrich_transactions_with_accounts


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


def load_by_type(transaction_type: str) -> pd.DataFrame:
    path = csv_path_for_type(transaction_type)
    rows = read_rows(path, TRANSACTION_FIELDS)
    if not rows:
        return pd.DataFrame(columns=TRANSACTION_FIELDS)
    return pd.DataFrame(rows).fillna("")


def load_all() -> pd.DataFrame:
    """Load all transaction CSVs into one normalized DataFrame."""
    frames = []

    for transaction_type in TRANSACTION_TYPES:
        df = load_by_type(transaction_type)
        if not df.empty:
            df["type"] = transaction_type
            frames.append(df)

    if not frames:
        return pd.DataFrame(columns=[*TRANSACTION_FIELDS, "type", "signed_amount"])

    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    df["signed_amount"] = df.apply(_signed_amount, axis=1)
    df = enrich_transactions_with_accounts(df)
    df = df.sort_values(by=["date", "created_at"], ascending=[False, False])
    return df


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
    transaction_type = tx.get("type")
    path = csv_path_for_type(transaction_type)
    rows = read_rows(path, TRANSACTION_FIELDS)

    row_id = next_numeric_id(rows)
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

    append_row(path, TRANSACTION_FIELDS, row)
    return int(row_id)


def update_transaction(tx_id: int | str, transaction_type: str, data: dict) -> bool:
    path = csv_path_for_type(transaction_type)
    rows = read_rows(path, TRANSACTION_FIELDS)
    changed = False
    editable_columns = [field for field in TRANSACTION_FIELDS if field != "id"]
    for row in rows:
        if str(row.get("id")) != str(tx_id):
            continue
        for col in editable_columns:
            if col in data:
                row[col] = _clean_cell(data[col])
        changed = True
        break
    if not changed:
        return False
    write_rows(path, TRANSACTION_FIELDS, rows)
    _notify_cache_changed()
    return True


def delete_transaction(tx_id: int | str, transaction_type: str) -> bool:
    path = csv_path_for_type(transaction_type)
    rows = read_rows(path, TRANSACTION_FIELDS)
    kept = [row for row in rows if str(row.get("id")) != str(tx_id)]
    if len(kept) == len(rows):
        return False
    write_rows(path, TRANSACTION_FIELDS, kept)
    _notify_cache_changed()
    return True


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
