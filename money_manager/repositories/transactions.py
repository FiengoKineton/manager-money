from datetime import datetime
from pathlib import Path

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
from money_manager.repositories.csv_files import append_row, ensure_csv, next_numeric_id, read_rows
from money_manager.services.account_service import enrich_transactions_with_accounts


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
    ensure_csv(path, TRANSACTION_FIELDS)
    df = pd.read_csv(path, dtype=str)
    if df.empty:
        return pd.DataFrame(columns=TRANSACTION_FIELDS)
    return df


def load_all() -> pd.DataFrame:
    """Load all transaction CSVs into one normalized DataFrame."""
    frames = []

    for transaction_type in TRANSACTION_TYPES:
        df = load_by_type(transaction_type)
        if not df.empty:
            df["type"] = transaction_type
            frames.append(df)

    if not frames:
        return pd.DataFrame(
            columns=[*TRANSACTION_FIELDS, "type", "signed_amount"]
        )

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
            "account_name_snapshot": "",
            "account_due_day_snapshot": "",
        }

    return {
        "account_key_snapshot": account_key,
        "account_name_snapshot": account_label_for_key(account_key),
        "account_due_day_snapshot": str(account_due_day_for_key(account_key, 15)),
    }


def append_transaction(tx: dict) -> int:
    transaction_type = tx.get("type")
    path = csv_path_for_type(transaction_type)
    rows = read_rows(path, TRANSACTION_FIELDS)

    row_id = next_numeric_id(rows)
    row = {
        "id": row_id,
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
        "account_key_snapshot": tx.get("account_key_snapshot", ""),
        "account_name_snapshot": tx.get("account_name_snapshot", ""),
        "account_due_day_snapshot": tx.get("account_due_day_snapshot", ""),
        "payment_method": tx.get("payment_method", ""),
        "contact_id": tx.get("contact_id", ""),
        "contact_name": tx.get("contact_name", ""),
        "iban_snapshot": tx.get("iban_snapshot", ""),
        "bic_swift_snapshot": tx.get("bic_swift_snapshot", ""),
        "bank_name_snapshot": tx.get("bank_name_snapshot", ""),
        "transfer_reference": tx.get("transfer_reference", ""),
        "transfer_status": tx.get("transfer_status", ""),
        "description": tx.get("description", ""),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }

    if not row["account_due_day_snapshot"]:
        row.update(_credit_account_snapshot_for_row({**row, "type": transaction_type}))

    append_row(path, TRANSACTION_FIELDS, row)
    return int(row_id)


def update_transaction(tx_id: int, transaction_type: str, data: dict) -> bool:
    path = csv_path_for_type(transaction_type)
    if not path.exists():
        return False

    ensure_csv(path, TRANSACTION_FIELDS)
    df = pd.read_csv(path)
    if "id" not in df.columns:
        return False

    mask = df["id"] == tx_id
    if not mask.any():
        return False

    editable_columns = [
        "date",
        "category",
        "sub_category",
        "amount",
        "original_amount",
        "original_currency",
        "exchange_rate_to_eur",
        "exchange_correction_to_eur",
        "exchange_effective_rate_to_eur",
        "account",
        "account_key_snapshot",
        "account_name_snapshot",
        "account_due_day_snapshot",
        "payment_method",
        "contact_id",
        "contact_name",
        "iban_snapshot",
        "bic_swift_snapshot",
        "bank_name_snapshot",
        "transfer_reference",
        "transfer_status",
        "description",
    ]
    for col in editable_columns:
        if col in data:
            df.loc[mask, col] = data[col]

    df.to_csv(path, index=False)
    _notify_cache_changed()
    return True


def delete_transaction(tx_id: int, transaction_type: str) -> bool:
    path = csv_path_for_type(transaction_type)
    if not path.exists():
        return False

    ensure_csv(path, TRANSACTION_FIELDS)
    df = pd.read_csv(path)
    if "id" not in df.columns:
        return False

    before = len(df)
    df = df[df["id"] != tx_id]
    if len(df) == before:
        return False

    df.to_csv(path, index=False)
    _notify_cache_changed()
    return True


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
