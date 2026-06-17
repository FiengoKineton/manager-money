"""Central facade for creating money movements.

This module does not replace the existing implementation yet.  It wraps current
services/repositories so future route code can use one clear entry point without
changing accounting rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from money_manager.domain.transaction import TransactionInput
from money_manager.repositories.transactions import append_transaction
from money_manager.services.transaction_service import save_new_transaction


@dataclass(frozen=True)
class MovementResult:
    ok: bool
    message: str = ""
    transaction_ids: tuple[int, ...] = ()
    pending_ids: tuple[int, ...] = ()
    error: str = ""
    raw: Mapping[str, Any] | None = None


def create_transaction_from_input(tx_input: TransactionInput) -> MovementResult:
    """Create a normal transaction using the existing transaction service."""
    result = save_new_transaction(tx_input)
    return _from_service_result(result)


def append_raw_transaction(tx: Mapping[str, Any]) -> MovementResult:
    """Append a transaction using the existing repository contract."""
    tx_id = append_transaction(dict(tx))
    return MovementResult(ok=True, message="Transaction saved.", transaction_ids=(int(tx_id),), raw={"id": tx_id})


def _from_service_result(result: Mapping[str, Any]) -> MovementResult:
    return MovementResult(
        ok=bool(result.get("ok")),
        message=str(result.get("message", "") or ""),
        error=str(result.get("error", "") or ""),
        transaction_ids=tuple(int(value) for value in result.get("transaction_ids", []) if str(value).isdigit()),
        pending_ids=tuple(int(value) for value in result.get("pending_ids", []) if str(value).isdigit()),
        raw=result,
    )
