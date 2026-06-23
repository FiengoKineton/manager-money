from __future__ import annotations

"""Payment routing domain objects used by the ledger foundation.

Sign convention used by the ledger layer:
- Asset accounts use positive balances.
- Money entering an asset account is positive; money leaving is negative.
- Liability accounts use negative balances for amounts owed.
- A credit-card purchase therefore creates a negative liability movement.
- A future settlement will create two movements: cash out from the settlement
  asset account and a positive liability decrease. Prompt 11C only previews that
  settlement; later prompts wire it into the existing Pending flow.
"""

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class LedgerMovementDraft:
    account_id: str
    account_name_snapshot: str
    movement_kind: str
    direction: str
    amount: float
    signed_amount: float
    effective_date: str
    status: str = "posted"
    notes: str = ""
    counterparty_account_id: str = ""
    counterparty_account_name_snapshot: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PaymentResolution:
    ok: bool
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    transaction_type: str = ""
    amount: float = 0.0
    currency: str = "EUR"
    transaction_date: str = ""
    account_id: str = ""
    account_name_snapshot: str = ""
    payment_method_id: str = ""
    payment_method_name_snapshot: str = ""
    linked_account_id: str = ""
    funding_account_id: str = ""
    settlement_account_id: str = ""
    liability_account_id: str = ""
    settlement_mode: str = ""
    due_date: str = ""
    due_day_snapshot: int | None = None
    statement_period: str = ""
    ledger_group_id: str = ""
    display_explanation: str = ""
    movements: list[LedgerMovementDraft] = field(default_factory=list)
    created_from_resolution: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["movements"] = [movement.to_dict() for movement in self.movements]
        return payload
