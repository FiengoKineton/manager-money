from datetime import date

import pandas as pd

from money_manager.config import CREDIT_ACCOUNT_KEYWORDS, CREDIT_CARD_DUE_DAY, TRANSACTION_TYPES, normalize_account_key
from money_manager.domain.transaction import TransactionInput
from money_manager.repositories.pending import append_pending
from money_manager.repositories.transactions import (
    append_transaction,
    delete_transaction,
    load_all,
    update_transaction,
)


def next_credit_due(payment_date=None, due_day: int = CREDIT_CARD_DUE_DAY) -> date:
    payment_date = payment_date or date.today()

    if payment_date.month == 12:
        return date(payment_date.year + 1, 1, due_day)

    return date(payment_date.year, payment_date.month + 1, due_day)


def save_new_transaction(tx_input: TransactionInput) -> None:
    tx = tx_input.as_dict()
    account = tx.get("account", "").strip().lower()

    if account in CREDIT_ACCOUNT_KEYWORDS:
        tx["account"] = "credit"
        try:
            payment_date = date.fromisoformat(tx_input.date)
        except (TypeError, ValueError):
            payment_date = date.today()

        append_pending(tx, next_credit_due(payment_date))
        return

    append_transaction(tx)


def load_transactions() -> pd.DataFrame:
    return load_all()


def prepare_transactions_for_display(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if df.empty:
        df["date_str"] = []
        df["amount_str"] = []
        df["row_index"] = []
        return df

    df["date_str"] = df["date"].dt.strftime("%Y-%m-%d")
    df["amount_str"] = df["amount"].map(lambda amount: f"{amount:.2f}")
    df["row_index"] = df.index
    return df


def transaction_detail_context(row_index: int) -> tuple[dict, list[str]]:
    from money_manager.config import categories_for

    df = load_all()

    try:
        row = df.loc[row_index]
    except KeyError as exc:
        raise LookupError(f"Transaction {row_index} not found") from exc

    date_str = row["date"].strftime("%Y-%m-%d") if hasattr(row["date"], "strftime") else str(row.get("date", ""))

    def clean(value):
        return "" if str(value) == "nan" else value

    tx = {
        "id": int(row_index),
        "csv_id": int(row["id"]),
        "type": row["type"],
        "date": date_str,
        "category": clean(row.get("category", "")),
        "sub_category": clean(row.get("sub_category", "")),
        "amount": f"{row['amount']:.2f}",
        "account": clean(row.get("account", "")),
        "account_key": clean(row.get("account_key", normalize_account_key(row.get("account", "")))),
        "account_label": clean(row.get("account_label", "")),
        "description": clean(row.get("description", "")),
    }

    return tx, categories_for(tx["type"])


def update_existing_transaction(row_index: int, form) -> None:
    df = load_all()
    row = df.loc[row_index]
    tx_input = TransactionInput.from_form({**form, "type": row["type"]})
    update_transaction(int(row["id"]), row["type"], {
        "date": tx_input.date,
        "category": tx_input.category,
        "sub_category": tx_input.sub_category,
        "amount": tx_input.amount,
        "account": tx_input.account,
        "description": tx_input.description,
    })


def delete_existing_transaction(row_index: int) -> None:
    df = load_all()
    row = df.loc[row_index]
    delete_transaction(int(row["id"]), row["type"])
