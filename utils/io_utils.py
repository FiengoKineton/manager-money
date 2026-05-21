# utils/io_utils.py
import csv
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List

import pandas as pd

from config import EXPENSES_CSV, INCOMES_CSV, INVESTMENTS_CSV, DEFAULT_TYPES



def next_credit_due(payment_date=None, due_day=15):
    """
    Credit card logic:
    every credit-card payment made in month M is charged on day `due_day`
    of month M+1.

    Examples:
    - 2026-02-12 -> 2026-03-15
    - 2026-02-28 -> 2026-03-15
    - 2026-03-02 -> 2026-04-15
    - 2026-05-06 -> 2026-06-15
    """
    payment_date = payment_date or date.today()

    if payment_date.month == 12:
        return date(payment_date.year + 1, 1, due_day)

    return date(payment_date.year, payment_date.month + 1, due_day)

def _ensure_csv(path: Path, fieldnames: List[str]) -> None:
    if not path.exists():
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()


def load_expenses() -> pd.DataFrame:
    cols = ["id", "date", "category", "sub_category", "amount",
            "account", "description", "created_at"]
    _ensure_csv(EXPENSES_CSV, cols)
    df = pd.read_csv(EXPENSES_CSV, dtype=str)
    if df.empty:
        return pd.DataFrame(columns=cols)
    return df


def load_incomes() -> pd.DataFrame:
    cols = ["id", "date", "category", "sub_category", "amount",
            "account", "description", "created_at"]
    _ensure_csv(INCOMES_CSV, cols)
    df = pd.read_csv(INCOMES_CSV, dtype=str)
    if df.empty:
        return pd.DataFrame(columns=cols)
    return df


def load_investments() -> pd.DataFrame:
    # Simple version: similar to expenses/incomes
    cols = ["id", "date", "category", "sub_category", "amount",
            "account", "description", "created_at"]
    _ensure_csv(INVESTMENTS_CSV, cols)
    df = pd.read_csv(INVESTMENTS_CSV, dtype=str)
    if df.empty:
        return pd.DataFrame(columns=cols)
    return df


def load_all() -> pd.DataFrame:
    """Load all CSVs and return unified DataFrame with a 'type' and 'signed_amount'."""
    ex = load_expenses()
    if not ex.empty:
        ex["type"] = "expense"

    inc = load_incomes()
    if not inc.empty:
        inc["type"] = "income"

    inv = load_investments()
    if not inv.empty:
        inv["type"] = "investment"

    frames = [df for df in (ex, inc, inv) if not df.empty]
    if not frames:
        cols = ["id", "date", "category", "sub_category", "amount",
                "account", "description", "created_at", "type", "signed_amount"]
        return pd.DataFrame(columns=cols)

    df = pd.concat(frames, ignore_index=True)

    # Parse date & amount
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")

    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)

    # Signed amount: incomes positive, expenses negative, investments negative (cash out)
    def _signed(row):
        if row["type"] == "income":
            return row["amount"]
        elif row["type"] == "expense":
            return -row["amount"]
        elif row["type"] == "investment":
            # simple: treat as cash out unless category is "Dividend"
            if str(row.get("category", "")).lower() == "dividend":
                return row["amount"]
            return -row["amount"]
        return 0.0

    df["signed_amount"] = df.apply(_signed, axis=1)

    # Sort by date desc, then created_at desc
    df = df.sort_values(by=["date", "created_at"], ascending=[False, False])

    return df


def _next_id(path: Path) -> int:
    """Incremental numeric id per CSV."""
    if not path.exists():
        return 1
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        ids = [int(row["id"]) for row in reader if row.get("id")]
    return max(ids) + 1 if ids else 1


def append_transaction(tx: Dict) -> None:
    """
    tx must contain:
    - type: 'expense' | 'income' | 'investment'
    - date, category, sub_category, amount, account, description
    """
    ttype = tx.get("type")
    if ttype not in DEFAULT_TYPES:
        raise ValueError(f"Unknown transaction type: {ttype}")

    if ttype == "expense":
        path = EXPENSES_CSV
    elif ttype == "income":
        path = INCOMES_CSV
    else:
        path = INVESTMENTS_CSV

    cols = ["id", "date", "category", "sub_category", "amount",
            "account", "description", "created_at"]
    _ensure_csv(path, cols)
    tx_id = _next_id(path)
    now = datetime.now().isoformat(timespec="seconds")

    row = {
        "id": tx_id,
        "date": tx.get("date", ""),
        "category": tx.get("category", ""),
        "sub_category": tx.get("sub_category", ""),
        "amount": str(tx.get("amount", "0")),
        "account": tx.get("account", ""),
        "description": tx.get("description", ""),
        "created_at": now,
    }

    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writerow(row)


def _csv_path_for_type(ttype: str) -> Path:
    if ttype == "expense":
        return EXPENSES_CSV
    elif ttype == "income":
        return INCOMES_CSV
    elif ttype == "investment":
        return INVESTMENTS_CSV
    else:
        raise ValueError(f"Unknown type: {ttype}")

def update_transaction_record(tx_id: int, ttype: str, data: dict) -> bool:
    """Update a single transaction in the underlying CSV."""
    path = _csv_path_for_type(ttype)
    if not path.exists():
        return False

    df = pd.read_csv(path)
    if "id" not in df.columns:
        return False

    mask = df["id"] == tx_id
    if not mask.any():
        return False

    for col in ["date", "category", "sub_category", "amount", "account", "description"]:
        if col in data:
            df.loc[mask, col] = data[col]

    df.to_csv(path, index=False)
    return True

def delete_transaction_record(tx_id: int, ttype: str) -> bool:
    """Delete a single transaction from the underlying CSV."""
    path = _csv_path_for_type(ttype)
    if not path.exists():
        return False

    df = pd.read_csv(path)
    if "id" not in df.columns:
        return False

    before = len(df)
    df = df[df["id"] != tx_id]
    if len(df) == before:
        return False

    df.to_csv(path, index=False)
    return True
