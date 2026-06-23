from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class TransactionUid:
    transaction_type: str
    tx_id: str


def make_transaction_uid(transaction_type: str, tx_id: int | str) -> str:
    """Return the stable ledger UID used to link CSV rows to ledger rows."""
    tx_type = str(transaction_type or "").strip().casefold()
    tx_id_text = str(tx_id or "").strip()
    if not tx_type or not tx_id_text:
        return ""
    return f"{tx_type}:{tx_id_text}"


def parse_transaction_uid(uid: str) -> TransactionUid | None:
    """Parse UIDs such as ``expense:123`` without raising on legacy blanks."""
    text = str(uid or "").strip()
    if not text or ":" not in text:
        return None
    tx_type, tx_id = text.split(":", 1)
    tx_type = tx_type.strip().casefold()
    tx_id = tx_id.strip()
    if not tx_type or not tx_id:
        return None
    return TransactionUid(transaction_type=tx_type, tx_id=tx_id)


@dataclass(slots=True)
class TransactionInput:
    type: str
    date: str
    category: str
    sub_category: str
    amount: float
    account: str
    description: str
    currency: str = "EUR"
    account_payment_method: str = ""
    account_insufficient_action: str = ""
    # Stable Prompt 11D routing fields. They are optional so legacy forms keep
    # using the v10 path until Prompt 11F migrates the whole UI.
    account_id: str = ""
    payment_method_id: str = ""
    payment_channel_method_id: str = ""
    force_payment_rebuild: bool = False
    confirm_settled_edit: bool = False
    # Backward-compatible aliases for old forms/templates.
    paypal_payment_method: str = ""
    paypal_insufficient_action: str = ""

    @classmethod
    def from_form(cls, form) -> "TransactionInput":
        amount_text = str(form.get("amount", "0")).replace(",", ".")
        try:
            amount = float(amount_text)
        except ValueError:
            amount = 0.0

        explicit_payment_method_id = str(form.get("payment_method_id", "") or "").strip()
        explicit_account_id = str(form.get("account_id", "") or "").strip()

        return cls(
            type=form.get("type", "expense"),
            date=form.get("date", ""),
            category=form.get("category", ""),
            sub_category=form.get("sub_category", ""),
            amount=amount,
            account=form.get("account", ""),
            description=form.get("description", ""),
            currency=str(form.get("currency", "EUR") or "EUR").upper(),
            account_payment_method=str(
                form.get("account_payment_method")
                or form.get("payment_method_route")
                or form.get("paypal_payment_method")
                or ""
            ).lower(),
            account_insufficient_action=str(
                form.get("account_insufficient_action")
                or form.get("insufficient_action")
                or form.get("paypal_insufficient_action")
                or ""
            ).lower(),
            account_id=explicit_account_id,
            payment_method_id=explicit_payment_method_id,
            payment_channel_method_id=str(form.get("payment_channel_method_id", "") or "").strip(),
            force_payment_rebuild=_truthy(form.get("force_payment_rebuild")),
            confirm_settled_edit=_truthy(form.get("confirm_settled_edit")),
            paypal_payment_method=str(form.get("paypal_payment_method", "") or "").lower(),
            paypal_insufficient_action=str(form.get("paypal_insufficient_action", "") or "").lower(),
        )

    def as_dict(self) -> dict:
        return {
            "type": self.type,
            "date": self.date,
            "category": self.category,
            "sub_category": self.sub_category,
            "amount": self.amount,
            "account": self.account,
            "account_id": self.account_id,
            "payment_method_id": self.payment_method_id,
            "payment_channel_method_id": self.payment_channel_method_id,
            "description": self.description,
            "currency": self.currency,
        }


def _truthy(value) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}
