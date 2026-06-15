from datetime import date, timedelta

import pandas as pd

from money_manager.config import (
    CREDIT_ACCOUNT_KEYWORDS,
    CREDIT_CARD_DUE_DAY,
    PAYPAL_ACCOUNT_KEY,
    PAYPAL_CREDIT_ACCOUNT_VALUE,
    TRANSACTION_TYPES,
    normalize_account_key,
)
from money_manager.domain.transaction import TransactionInput
from money_manager.services.currency_service import append_conversion_note, convert_amount_to_eur
from money_manager.repositories.pending import append_pending
from money_manager.repositories.transactions import (
    append_transaction,
    delete_transaction,
    load_all,
    update_transaction,
)

PAYPAL_METHOD_BALANCE = "balance"
PAYPAL_METHOD_CREDIT = "credit"
PAYPAL_METHOD_ANOTHER_CARD = "another_card"
PAYPAL_INSUFFICIENT_STOP = "stop"
PAYPAL_INSUFFICIENT_ANOTHER_CARD = "use_another_card_for_remaining"
PAYPAL_INSUFFICIENT_CREDIT = "use_credit_for_remaining"


def next_credit_due(payment_date=None, due_day: int = CREDIT_CARD_DUE_DAY) -> date:
    payment_date = payment_date or date.today()

    if payment_date.month == 12:
        return date(payment_date.year + 1, 1, due_day)

    return date(payment_date.year, payment_date.month + 1, due_day)


def save_new_transaction(tx_input: TransactionInput) -> dict:
    """Save a new transaction and return a small UI-friendly result.

    PayPal now has two layers:
    - account="PayPal" means the PayPal wallet balance;
    - paypal_payment_method="credit" creates a pending PayPal-credit row;
    - paypal_payment_method="another_card" records a main-bank/card outflow.
    """
    tx = _transaction_payload_in_eur(tx_input)
    account = str(tx.get("account", "")).strip().lower()

    if tx_input.type == "expense" and normalize_account_key(account) == PAYPAL_ACCOUNT_KEY:
        return _save_paypal_expense(tx, tx_input)

    if account in CREDIT_ACCOUNT_KEYWORDS:
        tx["account"] = "credit"
        append_pending(tx, _due_date_from_input(tx_input))
        return {"ok": True, "message": "Credit-card payment added to pending."}

    append_transaction(tx)
    return {"ok": True, "message": "Transaction saved."}


def paypal_balance() -> float:
    """Current balance of the PayPal auxiliary account."""
    from money_manager.services.account_service import account_balance_rows

    rows = account_balance_rows(load_all())
    for row in rows:
        if row.get("key") == PAYPAL_ACCOUNT_KEY:
            return float(row.get("balance", 0.0) or 0.0)
    return 0.0


def _save_paypal_expense(tx: dict, tx_input: TransactionInput) -> dict:
    method = tx_input.paypal_payment_method or PAYPAL_METHOD_BALANCE

    if method == PAYPAL_METHOD_CREDIT:
        _append_paypal_credit_pending(tx, _due_date_from_input(tx_input))
        return {"ok": True, "message": "PayPal credit payment added to pending."}

    if method == PAYPAL_METHOD_ANOTHER_CARD:
        main_tx = _with_note(tx, "PayPal checkout paid with another card/main bank route.")
        main_tx["account"] = ""
        append_transaction(main_tx)
        return {"ok": True, "message": "PayPal checkout saved as a main-bank/card expense."}

    # Default: spend from the PayPal wallet balance.
    amount = float(tx.get("amount", 0.0) or 0.0)
    balance = paypal_balance()
    if amount <= balance + 0.005:
        balance_tx = _with_note(tx, "Paid from PayPal balance.")
        balance_tx["account"] = "PayPal"
        append_transaction(balance_tx)
        return {"ok": True, "message": "PayPal balance expense saved."}

    remaining = max(0.0, amount - max(balance, 0.0))
    action = tx_input.paypal_insufficient_action or PAYPAL_INSUFFICIENT_STOP

    if action == PAYPAL_INSUFFICIENT_ANOTHER_CARD:
        if balance > 0.005:
            append_transaction(_paypal_balance_part(tx, balance, amount))
        main_tx = _with_amount(tx, remaining)
        main_tx = _with_note(main_tx, f"Remaining PayPal checkout paid with another card/main bank route after using € {max(balance, 0.0):.2f} PayPal balance.")
        main_tx["account"] = ""
        append_transaction(main_tx)
        return {"ok": True, "message": "PayPal balance used and remaining amount saved as main-bank/card expense."}

    if action == PAYPAL_INSUFFICIENT_CREDIT:
        if balance > 0.005:
            append_transaction(_paypal_balance_part(tx, balance, amount))
        pending_tx = _with_amount(tx, remaining)
        pending_tx = _with_note(pending_tx, f"Remaining PayPal checkout scheduled on credit after using € {max(balance, 0.0):.2f} PayPal balance.")
        _append_paypal_credit_pending(pending_tx, _due_date_from_input(tx_input))
        return {"ok": True, "message": "PayPal balance used and remaining amount added to pending credit."}

    return {
        "ok": False,
        "error": (
            f"PayPal balance is not enough: available € {balance:.2f}, "
            f"expense € {amount:.2f}, missing € {remaining:.2f}. "
            "Choose another PayPal method or choose how to split the remaining amount."
        ),
        "paypal_balance": balance,
        "paypal_missing": remaining,
    }


def _append_paypal_credit_pending(tx: dict, due: date) -> None:
    pending_tx = _with_note(tx, "PayPal checkout scheduled through PayPal credit/card route.")
    pending_tx["account"] = PAYPAL_CREDIT_ACCOUNT_VALUE
    append_pending(pending_tx, due)


def _paypal_balance_part(tx: dict, balance: float, original_amount: float) -> dict:
    part = _with_amount(tx, max(balance, 0.0))
    part = _with_note(part, f"Partial PayPal balance payment for € {original_amount:.2f} checkout.")
    part["account"] = "PayPal"
    return part


def _with_amount(tx: dict, amount: float) -> dict:
    updated = dict(tx)
    updated["amount"] = round(float(amount or 0.0), 2)
    return updated


def _with_note(tx: dict, note: str) -> dict:
    updated = dict(tx)
    description = str(updated.get("description", "") or "").strip()
    updated["description"] = f"{description} [{note}]" if description else note
    return updated


def _due_date_from_input(tx_input: TransactionInput) -> date:
    try:
        payment_date = date.fromisoformat(tx_input.date)
    except (TypeError, ValueError):
        payment_date = date.today()
    return next_credit_due(payment_date)


def _transaction_payload_in_eur(tx_input: TransactionInput) -> dict:
    tx = tx_input.as_dict()
    conversion = convert_amount_to_eur(tx_input.amount, tx_input.currency)
    tx["amount"] = conversion["amount_eur"]
    tx["description"] = append_conversion_note(tx_input.description, conversion)

    if conversion.get("is_conversion"):
        tx["original_amount"] = f"{conversion['original_amount']:.2f}"
        tx["original_currency"] = conversion["original_currency"]
        tx["exchange_rate_to_eur"] = f"{conversion['rate_to_eur']:.8f}"
        tx["exchange_correction_to_eur"] = f"{conversion['correction_to_eur']:.8f}"
        tx["exchange_effective_rate_to_eur"] = f"{conversion['effective_rate_to_eur']:.8f}"
    else:
        tx["original_amount"] = ""
        tx["original_currency"] = "EUR"
        tx["exchange_rate_to_eur"] = "1.00000000"
        tx["exchange_correction_to_eur"] = "0.00000000"
        tx["exchange_effective_rate_to_eur"] = "1.00000000"
    tx.pop("currency", None)
    return tx


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
    df["delay_date_default"] = (date.today() + timedelta(days=1)).isoformat()
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
        "original_amount": clean(row.get("original_amount", "")),
        "original_currency": clean(row.get("original_currency", "")),
        "exchange_rate_to_eur": clean(row.get("exchange_rate_to_eur", "")),
        "exchange_correction_to_eur": clean(row.get("exchange_correction_to_eur", "")),
        "exchange_effective_rate_to_eur": clean(row.get("exchange_effective_rate_to_eur", "")),
        "account": clean(row.get("account", "")),
        "account_key": clean(row.get("account_key", normalize_account_key(row.get("account", "")))),
        "account_label": clean(row.get("account_label", "")),
        "description": clean(row.get("description", "")),
        "delay_date_default": (date.today() + timedelta(days=1)).isoformat(),
    }

    return tx, categories_for(tx["type"])


def delay_existing_transaction(row_index: int, new_date: str) -> None:
    if not new_date:
        return

    df = load_all()
    row = df.loc[row_index]

    update_transaction(
        int(row["id"]),
        row["type"],
        {"date": new_date},
    )


def update_existing_transaction(row_index: int, form) -> None:
    df = load_all()
    row = df.loc[row_index]
    tx_input = TransactionInput.from_form({**form, "type": row["type"]})

    data = {
        "date": tx_input.date,
        "category": tx_input.category,
        "sub_category": tx_input.sub_category,
        "amount": tx_input.amount,
        "account": tx_input.account,
        "description": tx_input.description,
    }

    # The transaction detail screen edits the already-saved EUR value.  The add
    # screen has the currency selector and passes currency explicitly, so only
    # re-run conversion when that field is present.
    if "currency" in form:
        converted = _transaction_payload_in_eur(tx_input)
        data.update({
            "amount": converted["amount"],
            "description": converted["description"],
            "original_amount": converted.get("original_amount", ""),
            "original_currency": converted.get("original_currency", ""),
            "exchange_rate_to_eur": converted.get("exchange_rate_to_eur", ""),
            "exchange_correction_to_eur": converted.get("exchange_correction_to_eur", ""),
            "exchange_effective_rate_to_eur": converted.get("exchange_effective_rate_to_eur", ""),
        })

    update_transaction(int(row["id"]), row["type"], data)


def delete_existing_transaction(row_index: int) -> None:
    df = load_all()
    row = df.loc[row_index]
    delete_transaction(int(row["id"]), row["type"])
