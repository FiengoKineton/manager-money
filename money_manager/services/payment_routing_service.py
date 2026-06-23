from __future__ import annotations

"""Central payment routing engine for Prompt 11C.

This module resolves *how* a transaction should touch account balances, but it
never writes CSV files. Callers can inspect the returned PaymentResolution and
choose whether/when to persist the ledger movements.

Ledger sign convention:
- Asset accounts use positive balances.
- Expenses reduce assets with negative signed_amount.
- Income increases assets with positive signed_amount.
- Liabilities are stored as negative balances. A credit-card purchase increases
  what is owed with a negative signed_amount on the liability account.
"""

import calendar
import json
import uuid
from datetime import date as date_cls, datetime
from typing import Any, Mapping

from money_manager.domain.payment import LedgerMovementDraft, PaymentResolution
from money_manager.services.account_config_service import (
    MAIN_ACCOUNT_KEY,
    account_by_key,
    active_accounts,
    all_accounts,
    clean_text,
)
from money_manager.services.payment_method_service import (
    active_payment_methods,
    payment_method_by_id,
    normalize_payment_method_id,
)

ASSET_ACCOUNT_KINDS = {
    "current_account",
    "cash",
    "prepaid_balance",
    "wallet_balance",
    "dependent_wallet",
    "meal_voucher",
    "investment_cash",
    "other",
}

IMMEDIATE_EXPENSE_METHOD_TYPES = {"debit_card", "bank_transfer"}
STORED_BALANCE_METHOD_TYPES = {"cash", "prepaid_card", "meal_voucher", "wallet_balance", "investment_cash_transfer"}


def resolve_payment(
    transaction_type: str,
    amount: float,
    date: str | date_cls | datetime,
    account_id: str | None = None,
    payment_method_id: str | None = None,
    category: str | None = None,
    sub_category: str | None = None,
    description: str = "",
    existing_row: Mapping[str, Any] | None = None,
    user_id: str | None = None,
) -> PaymentResolution:
    """Resolve payment route into deterministic ledger movement drafts.

    This is intentionally side-effect free: no transaction CSV, pending CSV, or
    ledger CSV is written here.
    """
    tx_type = clean_text(transaction_type)
    tx_date = _coerce_date(date)
    amount_value = _money(amount)
    currency = _currency_from_existing(existing_row) or "EUR"
    group_id = f"lg_{uuid.uuid4().hex}"

    resolution = PaymentResolution(
        ok=True,
        transaction_type=tx_type,
        amount=amount_value,
        currency=currency,
        transaction_date=tx_date.isoformat(),
        ledger_group_id=group_id,
    )

    if tx_type not in {"income", "expense", "investment"}:
        return _error(resolution, f"Unsupported transaction_type: {transaction_type}")
    if amount_value <= 0:
        return _error(resolution, "Amount must be greater than zero.")

    accounts = active_accounts(user_id=user_id, include_main=True)
    if not accounts:
        return _error(resolution, "No active accounts are configured for this user.")

    legacy_method_id = _legacy_payment_method_id_for_account_value(account_id, user_id=user_id)
    effective_payment_method_id = payment_method_id or legacy_method_id
    effective_account_id = None if legacy_method_id and not payment_method_id else account_id
    if account_id and not legacy_method_id and not _strict_account_by_key(account_id, user_id=user_id):
        return _error(resolution, f"Unknown or inactive account: {account_id}")

    method = _resolve_method(effective_payment_method_id, tx_type=tx_type, account_id=effective_account_id, user_id=user_id)
    if effective_payment_method_id and method is None:
        return _error(resolution, f"Unknown or inactive payment method: {effective_payment_method_id}")
    if legacy_method_id:
        resolution.warnings.append(f"Legacy account value {account_id!r} was resolved through payment method {legacy_method_id}.")
    if method and (method.get("validation_errors") or not method.get("is_active", True) or method.get("is_archived")):
        resolution.warnings.append(f"Payment method has validation issues: {', '.join(method.get('validation_errors', []))}")

    # Delegated wrappers such as PayPal via Credit Card preserve the visible
    # channel but recurse into the real settlement method.
    if method and method.get("settlement_mode") == "delegated":
        return _resolve_delegated(
            resolution,
            method=method,
            tx_type=tx_type,
            amount=amount_value,
            tx_date=tx_date,
            account_id=effective_account_id,
            category=category,
            sub_category=sub_category,
            description=description,
            existing_row=existing_row,
            user_id=user_id,
        )

    if tx_type == "income":
        return _resolve_income(resolution, amount_value, tx_date, effective_account_id, method, user_id=user_id)
    if tx_type == "expense":
        return _resolve_expense(resolution, amount_value, tx_date, effective_account_id, method, user_id=user_id)
    return _resolve_investment(resolution, amount_value, tx_date, effective_account_id, method, category=category, user_id=user_id)


def compute_statement_period(transaction_date: str | date_cls | datetime, statement_day: int | None = None) -> str:
    """Return a stable YYYY-MM statement period for a transaction date.

    If statement_day is null, statements follow the calendar month.  If it is
    set, dates after that day belong to the next statement period.
    """
    tx_date = _coerce_date(transaction_date)
    day = _valid_day(statement_day)
    if not day:
        return f"{tx_date.year:04d}-{tx_date.month:02d}"
    if tx_date.day > day:
        year, month = _add_months(tx_date.year, tx_date.month, 1)
        return f"{year:04d}-{month:02d}"
    return f"{tx_date.year:04d}-{tx_date.month:02d}"


def compute_due_date(
    transaction_date: str | date_cls | datetime,
    due_day: int,
    statement_day: int | None = None,
    policy: str = "next_month",
) -> str:
    """Compute the credit due date while preserving due-day snapshots.

    ``policy='next_month'`` means the due date is due_day in the month after the
    statement period. Other policies currently fall back to same-month statement
    due dates and are intentionally conservative until the settlement prompt.
    """
    tx_date = _coerce_date(transaction_date)
    day = _valid_day(due_day) or 15
    period = compute_statement_period(tx_date, statement_day=statement_day)
    year, month = [int(part) for part in period.split("-", 1)]
    if clean_text(policy) == "next_month":
        year, month = _add_months(year, month, 1)
    return date_cls(year, month, min(day, calendar.monthrange(year, month)[1])).isoformat()


def resolution_to_jsonable(resolution: PaymentResolution) -> dict[str, Any]:
    payload = resolution.to_dict()
    # Avoid recursive duplication if a caller already attached an expanded copy.
    payload.pop("created_from_resolution", None)
    return payload


def _resolve_income(
    resolution: PaymentResolution,
    amount: float,
    tx_date: date_cls,
    account_id: str | None,
    method: Mapping[str, Any] | None,
    *,
    user_id: str | None,
) -> PaymentResolution:
    account = _account_or_default(account_id or _method_account(method) or MAIN_ACCOUNT_KEY, user_id=user_id)
    if not account:
        return _error(resolution, "No valid income account could be resolved.")
    account_kind = str(account.get("account_kind") or account.get("type") or "")
    if account_kind not in ASSET_ACCOUNT_KINDS and account_kind != "current_account":
        resolution.warnings.append(f"Income routed to non-asset account kind: {account_kind}")
    _set_account_snapshot(resolution, account)
    _set_method_snapshot(resolution, method)
    resolution.funding_account_id = str(account.get("key") or account.get("id") or "")
    resolution.settlement_account_id = resolution.funding_account_id
    resolution.settlement_mode = str(method.get("settlement_mode") if method else "immediate")
    resolution.display_explanation = f"Income increases {resolution.account_name_snapshot} immediately."
    resolution.movements.append(_movement(
        account=account,
        movement_kind="income_cash_in",
        direction="in",
        amount=amount,
        signed_amount=amount,
        effective_date=tx_date,
        notes=resolution.display_explanation,
    ))
    return _finalize(resolution)


def _resolve_expense(
    resolution: PaymentResolution,
    amount: float,
    tx_date: date_cls,
    account_id: str | None,
    method: Mapping[str, Any] | None,
    *,
    user_id: str | None,
) -> PaymentResolution:
    if method is None:
        account_hint = _account_or_default(account_id, user_id=user_id) if account_id else None
        method = _default_method_for_account_or_type(account_hint, user_id=user_id)

    if method is None:
        method = _default_expense_method(user_id=user_id)
    if method is None:
        return _error(resolution, "No active payment method could be resolved for this expense.")

    method_type = str(method.get("method_type") or "")
    settlement_mode = str(method.get("settlement_mode") or "")
    _set_method_snapshot(resolution, method)
    resolution.settlement_mode = settlement_mode
    resolution.linked_account_id = str(method.get("linked_account_id") or "")
    resolution.funding_account_id = str(method.get("funding_account_id") or "")
    resolution.settlement_account_id = str(method.get("settlement_account_id") or "")
    resolution.liability_account_id = str(method.get("liability_account_id") or "")

    if settlement_mode == "external_record_only" or method_type == "other":
        resolution.warnings.append("No tracked balance was affected because this payment method is external_record_only.")
        resolution.display_explanation = "Recorded for transaction history only; no ledger movement was created."
        return _finalize(resolution)

    if settlement_mode == "delayed" or method_type == "credit_card":
        return _resolve_credit_expense(resolution, amount, tx_date, method, user_id=user_id)

    if method_type in IMMEDIATE_EXPENSE_METHOD_TYPES or settlement_mode == "immediate":
        account = _account_or_default(method.get("funding_account_id") or account_id or MAIN_ACCOUNT_KEY, user_id=user_id)
        if not account:
            return _error(resolution, "Immediate expense has no valid funding account.")
        _set_account_snapshot(resolution, account)
        resolution.funding_account_id = str(account.get("key") or account.get("id") or "")
        resolution.display_explanation = f"Expense deducts € {amount:.2f} from {resolution.account_name_snapshot} immediately."
        resolution.movements.append(_movement(
            account=account,
            movement_kind="expense_cash_out",
            direction="out",
            amount=amount,
            signed_amount=-amount,
            effective_date=tx_date,
            notes=resolution.display_explanation,
        ))
        return _finalize(resolution)

    if method_type in STORED_BALANCE_METHOD_TYPES or settlement_mode == "stored_balance":
        account = _account_or_default(method.get("funding_account_id") or method.get("linked_account_id") or account_id, user_id=user_id)
        if not account:
            return _error(resolution, "Stored-balance expense has no valid linked account.")
        movement_kind = {
            "cash": "expense_cash_out",
            "prepaid_card": "expense_cash_out",
            "meal_voucher": "expense_cash_out",
            "wallet_balance": "expense_cash_out",
            "investment_cash_transfer": "investment_cash_out",
        }.get(method_type, "expense_cash_out")
        _set_account_snapshot(resolution, account)
        resolution.linked_account_id = str(account.get("key") or account.get("id") or "")
        resolution.funding_account_id = resolution.linked_account_id
        resolution.settlement_account_id = resolution.linked_account_id
        resolution.display_explanation = f"Expense deducts € {amount:.2f} from {resolution.account_name_snapshot} stored balance immediately."
        resolution.movements.append(_movement(
            account=account,
            movement_kind=movement_kind,
            direction="out",
            amount=amount,
            signed_amount=-amount,
            effective_date=tx_date,
            notes=resolution.display_explanation,
        ))
        return _finalize(resolution)

    resolution.warnings.append(f"Unhandled method_type={method_type!r}, settlement_mode={settlement_mode!r}; no movement created.")
    resolution.display_explanation = "Payment route was recognized but not ledger-posted yet."
    return _finalize(resolution)


def _resolve_credit_expense(
    resolution: PaymentResolution,
    amount: float,
    tx_date: date_cls,
    method: Mapping[str, Any],
    *,
    user_id: str | None,
) -> PaymentResolution:
    liability_account = _account_or_default(method.get("liability_account_id") or "credit_card", user_id=user_id)
    if not liability_account:
        return _error(resolution, "Credit-card payment method has no valid liability account.")
    rules = method.get("rules") if isinstance(method.get("rules"), Mapping) else {}
    due_day = _valid_day(rules.get("due_day")) or 15
    statement_day = _valid_day(rules.get("statement_day"))
    policy = str(rules.get("settlement_day_policy") or "next_month")
    resolution.liability_account_id = str(liability_account.get("key") or liability_account.get("id") or "")
    resolution.settlement_account_id = str(method.get("settlement_account_id") or method.get("funding_account_id") or "")
    resolution.funding_account_id = str(method.get("funding_account_id") or resolution.settlement_account_id)
    resolution.account_id = resolution.liability_account_id
    resolution.account_name_snapshot = str(liability_account.get("label") or liability_account.get("name") or resolution.liability_account_id)
    resolution.due_day_snapshot = due_day
    resolution.statement_period = compute_statement_period(tx_date, statement_day=statement_day)
    resolution.due_date = compute_due_date(tx_date, due_day=due_day, statement_day=statement_day, policy=policy)
    resolution.display_explanation = (
        f"Credit expense increases {resolution.account_name_snapshot} liability now; "
        f"cash settlement from {resolution.settlement_account_id or 'settlement account'} is due {resolution.due_date}."
    )
    resolution.movements.append(_movement(
        account=liability_account,
        movement_kind="credit_liability_increase",
        direction="liability_increase",
        amount=amount,
        signed_amount=-amount,
        effective_date=tx_date,
        notes=resolution.display_explanation,
    ))
    return _finalize(resolution)


def _resolve_investment(
    resolution: PaymentResolution,
    amount: float,
    tx_date: date_cls,
    account_id: str | None,
    method: Mapping[str, Any] | None,
    *,
    category: str | None,
    user_id: str | None,
) -> PaymentResolution:
    # Keep v10 behavior conservative: dividends are cash-in; other investment
    # rows are cash-out from the selected/default funding account.
    is_dividend = clean_text(category) == "dividend"
    account = _account_or_default(account_id or _method_account(method) or MAIN_ACCOUNT_KEY, user_id=user_id)
    if not account:
        return _error(resolution, "No valid investment account could be resolved.")
    _set_account_snapshot(resolution, account)
    _set_method_snapshot(resolution, method)
    signed = amount if is_dividend else -amount
    kind = "income_cash_in" if is_dividend else "investment_cash_out"
    direction = "in" if is_dividend else "out"
    resolution.display_explanation = f"Investment {'dividend increases' if is_dividend else 'cash movement affects'} {resolution.account_name_snapshot}."
    resolution.movements.append(_movement(
        account=account,
        movement_kind=kind,
        direction=direction,
        amount=amount,
        signed_amount=signed,
        effective_date=tx_date,
        notes=resolution.display_explanation,
    ))
    return _finalize(resolution)


def _resolve_delegated(
    resolution: PaymentResolution,
    *,
    method: Mapping[str, Any],
    tx_type: str,
    amount: float,
    tx_date: date_cls,
    account_id: str | None,
    category: str | None,
    sub_category: str | None,
    description: str,
    existing_row: Mapping[str, Any] | None,
    user_id: str | None,
) -> PaymentResolution:
    wrapper_id = str(method.get("id") or "")
    delegate_id = str(method.get("delegates_to_payment_method_id") or "")
    if not delegate_id:
        return _error(resolution, f"Delegated method {wrapper_id} has no delegate.")
    delegated = payment_method_by_id(delegate_id, include_archived=False, user_id=user_id)
    if not delegated:
        return _error(resolution, f"Delegated method {wrapper_id} points to missing/inactive {delegate_id}.")

    delegated_resolution = resolve_payment(
        tx_type,
        amount,
        tx_date,
        account_id=account_id,
        payment_method_id=delegate_id,
        category=category,
        sub_category=sub_category,
        description=description,
        existing_row=existing_row,
        user_id=user_id,
    )
    delegated_resolution.ledger_group_id = resolution.ledger_group_id
    delegated_resolution.warnings = [*resolution.warnings, *delegated_resolution.warnings]
    delegated_resolution.payment_method_id = wrapper_id
    delegated_resolution.payment_method_name_snapshot = str(method.get("name") or wrapper_id)
    delegated_resolution.linked_account_id = str(method.get("linked_account_id") or delegated_resolution.linked_account_id or "")
    delegated_resolution.warnings.insert(0, f"Delegated payment via {delegated_resolution.payment_method_name_snapshot}; actual settlement uses {delegated.get('name') or delegate_id}.")
    delegated_resolution.created_from_resolution.update({
        "wrapper_payment_method_id": wrapper_id,
        "wrapper_payment_method_name_snapshot": str(method.get("name") or wrapper_id),
        "delegates_to_payment_method_id": delegate_id,
        "delegated_payment_method_name_snapshot": str(delegated.get("name") or delegate_id),
    })
    if wrapper_id and delegated_resolution.display_explanation:
        delegated_resolution.display_explanation = f"{method.get('name') or wrapper_id} is only the channel. {delegated_resolution.display_explanation}"
    return _finalize(delegated_resolution)


def _finalize(resolution: PaymentResolution) -> PaymentResolution:
    resolution.amount = _money(resolution.amount)
    for movement in resolution.movements:
        movement.amount = _money(movement.amount)
        movement.signed_amount = _money(movement.signed_amount)
    base = resolution.to_dict()
    base.pop("created_from_resolution", None)
    base.pop("movements", None)
    base["movement_count"] = len(resolution.movements)
    resolution.created_from_resolution = base
    return resolution


def _error(resolution: PaymentResolution, message: str) -> PaymentResolution:
    resolution.ok = False
    resolution.errors.append(message)
    resolution.display_explanation = message
    return _finalize(resolution)


def _movement(
    *,
    account: Mapping[str, Any],
    movement_kind: str,
    direction: str,
    amount: float,
    signed_amount: float,
    effective_date: date_cls,
    notes: str = "",
    status: str = "posted",
) -> LedgerMovementDraft:
    account_id = str(account.get("key") or account.get("id") or "")
    return LedgerMovementDraft(
        account_id=account_id,
        account_name_snapshot=str(account.get("label") or account.get("name") or account_id),
        movement_kind=movement_kind,
        direction=direction,
        amount=_money(amount),
        signed_amount=_money(signed_amount),
        effective_date=effective_date.isoformat(),
        status=status,
        notes=notes,
    )


def _set_account_snapshot(resolution: PaymentResolution, account: Mapping[str, Any]) -> None:
    account_id = str(account.get("key") or account.get("id") or "")
    resolution.account_id = account_id
    resolution.account_name_snapshot = str(account.get("label") or account.get("name") or account_id)


def _set_method_snapshot(resolution: PaymentResolution, method: Mapping[str, Any] | None) -> None:
    if not method:
        return
    resolution.payment_method_id = str(method.get("id") or "")
    resolution.payment_method_name_snapshot = str(method.get("name") or resolution.payment_method_id)



def _legacy_payment_method_id_for_account_value(account_id: str | None, *, user_id: str | None) -> str:
    text = clean_text(account_id)
    if not text:
        return ""
    paypal_credit_aliases = {"paypal_credit", "paypal credit", "pay pal credit", "paypal card", "pay pal card"}
    credit_aliases = {"credit", "card", "credit card", "credit cards", "carta credito", "carta di credito"}
    if text in paypal_credit_aliases:
        return "paypal_via_credit_card" if payment_method_by_id("paypal_via_credit_card", include_archived=False, user_id=user_id) else "credit_card"
    if text in credit_aliases:
        return "credit_card"
    return ""

def _resolve_method(payment_method_id: str | None, *, tx_type: str, account_id: str | None, user_id: str | None) -> dict[str, Any] | None:
    if payment_method_id:
        normalized = normalize_payment_method_id(payment_method_id, user_id=user_id)
        return payment_method_by_id(normalized, include_archived=False, user_id=user_id)
    account = _account_or_default(account_id, user_id=user_id) if account_id else None
    return _default_method_for_account_or_type(account, tx_type=tx_type, user_id=user_id)


def _default_method_for_account_or_type(account: Mapping[str, Any] | None, *, tx_type: str = "expense", user_id: str | None) -> dict[str, Any] | None:
    if account:
        key = str(account.get("key") or account.get("id") or "")
        kind = str(account.get("account_kind") or account.get("type") or "")
        for method in active_payment_methods(user_id=user_id):
            if key and key in {
                str(method.get("linked_account_id") or ""),
                str(method.get("funding_account_id") or ""),
                str(method.get("settlement_account_id") or ""),
                str(method.get("liability_account_id") or ""),
            }:
                return method
        if kind == "credit_card_liability":
            return payment_method_by_id("credit_card", include_archived=False, user_id=user_id)
        if kind == "cash":
            return payment_method_by_id("cash", include_archived=False, user_id=user_id)
        if kind == "prepaid_balance":
            return payment_method_by_id("pre_paid_card", include_archived=False, user_id=user_id)
        if kind == "meal_voucher":
            return payment_method_by_id("edenred", include_archived=False, user_id=user_id)
        if key == MAIN_ACCOUNT_KEY or kind == "current_account":
            return payment_method_by_id("main_bank_transfer", include_archived=False, user_id=user_id)
    return _default_expense_method(user_id=user_id) if tx_type == "expense" else payment_method_by_id("main_bank_transfer", include_archived=False, user_id=user_id)


def _default_expense_method(user_id: str | None) -> dict[str, Any] | None:
    methods = active_payment_methods(user_id=user_id)
    for method in methods:
        if method.get("is_default"):
            return method
    for wanted in ("main_bank_transfer", "cash", "credit_card"):
        method = payment_method_by_id(wanted, include_archived=False, user_id=user_id)
        if method:
            return method
    return methods[0] if methods else None


def _method_account(method: Mapping[str, Any] | None) -> str:
    if not method:
        return ""
    return str(method.get("funding_account_id") or method.get("linked_account_id") or method.get("settlement_account_id") or method.get("liability_account_id") or "")


def _account_or_default(account_id: str | None, *, user_id: str | None) -> dict[str, Any] | None:
    if account_id and str(account_id).strip():
        return _strict_account_by_key(account_id, user_id=user_id)
    return account_by_key(MAIN_ACCOUNT_KEY, user_id=user_id, include_archived=True)


def _strict_account_by_key(account_id: str | None, *, user_id: str | None) -> dict[str, Any] | None:
    text = clean_text(account_id)
    if text in {"", "auto", "main", "bank", "main bank", "main bank account", "bank account", "conto", "conto corrente"}:
        return account_by_key(MAIN_ACCOUNT_KEY, user_id=user_id, include_archived=True)
    for account in all_accounts(user_id=user_id, include_archived=True, include_main=True):
        values = [account.get("id"), account.get("key"), account.get("label"), account.get("name"), *account.get("aliases", [])]
        if any(clean_text(value) == text for value in values):
            return account
    return None


def _coerce_date(value: str | date_cls | datetime) -> date_cls:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date_cls):
        return value
    text = str(value or "").strip()
    if not text:
        return date_cls.today()
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        try:
            return date_cls.fromisoformat(text[:10])
        except ValueError:
            return date_cls.today()


def _valid_day(value: Any) -> int | None:
    try:
        day = int(str(value or "").strip())
    except (TypeError, ValueError):
        return None
    return day if 1 <= day <= 31 else None


def _add_months(year: int, month: int, months: int) -> tuple[int, int]:
    zero_based = (year * 12 + (month - 1)) + months
    return zero_based // 12, zero_based % 12 + 1


def _money(value: Any) -> float:
    try:
        return round(float(str(value).replace(",", ".")), 2)
    except (TypeError, ValueError):
        return 0.0


def _currency_from_existing(existing_row: Mapping[str, Any] | None) -> str:
    if not existing_row:
        return ""
    currency = str(existing_row.get("original_currency") or existing_row.get("currency") or "").upper().strip()
    return currency or "EUR"


def resolution_json_dumps(resolution: PaymentResolution) -> str:
    return json.dumps(resolution_to_jsonable(resolution), ensure_ascii=False, sort_keys=True)
