from dataclasses import dataclass


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

    @classmethod
    def from_form(cls, form) -> "TransactionInput":
        amount_text = str(form.get("amount", "0")).replace(",", ".")
        try:
            amount = float(amount_text)
        except ValueError:
            amount = 0.0

        return cls(
            type=form.get("type", "expense"),
            date=form.get("date", ""),
            category=form.get("category", ""),
            sub_category=form.get("sub_category", ""),
            amount=amount,
            account=form.get("account", ""),
            description=form.get("description", ""),
            currency=str(form.get("currency", "EUR") or "EUR").upper(),
        )

    def as_dict(self) -> dict:
        return {
            "type": self.type,
            "date": self.date,
            "category": self.category,
            "sub_category": self.sub_category,
            "amount": self.amount,
            "account": self.account,
            "description": self.description,
            "currency": self.currency,
        }
