from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from money_manager.config import (
    CREDIT_ACCOUNT_KEYWORDS,
    CREDIT_CARD_PAYMENT_CATEGORY,
    MAIN_NET_CREDIT_PENDING,
    MAIN_NET_SEPARATE,
    PAYPAL_CREDIT_ALIASES,
    PAYPAL_CREDIT_ACCOUNT_VALUE,
    account_due_day_for_key,
    account_label_for_key,
    account_label_for_value,
    account_policy_for_key,
    is_auxiliary_account,
    normalize_account_key,
)
from money_manager.repositories.pending import load_pending, mark_executed, append_pending, write_pending
from money_manager.repositories.transactions import append_transaction
from money_manager.services.transaction_service import save_transaction_payload

CREDIT_STATEMENT_SOURCE = "credit_account_statement"
CREDIT_STATEMENT_KIND = "credit_statement"


def pending_total(rows: list[dict], include_auxiliary: bool = False) -> float:
    """Net amount expected to leave the main account.

    Expenses and investments increase the pending outflow. Pending income is
    treated as money expected to arrive, so it lowers the net outflow. Auxiliary
    accounts are skipped by default because they are tracked separately.

    Credit-account statement rows are included because they represent a future
    main-bank payment even though the purchases were logged separately on their
    real purchase dates.
    """
    total = 0.0
    for tx in rows:
        if tx.get("status") != "pending":
            continue
        if not include_auxiliary and _is_separate_auxiliary_pending(tx.get("account", "")):
            continue

        try:
            amount = float(tx.get("amount", 0.0))
        except (TypeError, ValueError):
            continue

        tx_type = str(tx.get("type", "expense")).lower()
        if tx_type == "income":
            total -= amount
        else:
            total += amount
    return total


def prepare_pending_for_display(rows: list[dict]) -> dict:
    """Sort pending items first, then executed items, and add UI helpers."""
    prepared = [_decorate_pending_row(row) for row in rows]
    pending_rows = sorted(
        [row for row in prepared if row["status"] == "pending"],
        key=lambda row: (row["date_due_sort"], row["category"], row["description"]),
    )
    executed_rows = sorted(
        [row for row in prepared if row["status"] != "pending"],
        key=lambda row: (row["date_due_sort"], row["category"], row["description"]),
        reverse=True,
    )

    pending_income = sum(row["amount_value"] for row in pending_rows if row["type"] == "income")
    pending_outflow = sum(row["amount_value"] for row in pending_rows if row["type"] != "income")
    auxiliary_pending = sum(row["amount_value"] for row in pending_rows if row["is_auxiliary_account"])
    next_pending_date = pending_rows[0]["date_due_str"] if pending_rows else "—"

    return {
        "all": [*pending_rows, *executed_rows],
        "pending": pending_rows,
        "executed": executed_rows,
        "pending_total": pending_total(rows, include_auxiliary=True),
        "main_pending_total": pending_total(rows, include_auxiliary=False),
        "pending_income": float(pending_income),
        "pending_outflow": float(pending_outflow),
        "auxiliary_pending": float(auxiliary_pending),
        "next_pending_date": next_pending_date,
    }


def execute_pending_by_id(tx_id: int | str, execution_date: str | None = None) -> bool:
    """Execute one open pending row.

    New credit-settlement rows are executed by credit_settlement_service so the
    ledger receives the cash-out and liability-decrease pair exactly once.
    """
    for tx in load_pending():
        if str(tx.get("id", "")) != str(tx_id):
            continue
        if str(tx.get("status", "pending")).lower() != "pending":
            return False
        if tx.get("source") == "credit_settlement":
            from money_manager.services.credit_settlement_service import execute_credit_settlement

            result = execute_credit_settlement(tx.get("source_id", ""), execution_date=execution_date)
            return bool(result.get("ok"))
        _execute_pending_row(tx, execution_date=execution_date)
        mark_executed(int(tx["id"]))
        return True
    return False


def process_pending(today: date | None = None, credit_only: bool = False) -> int:
    """Execute pending rows due up to today.

    Opening the Pending page first syncs credit-account statement rows. This
    function then auto-executes only credit-style rows when credit_only=True, to
    preserve the app's old behavior. Manual pending/recurring/debt rows stay
    manual unless credit_only=False.
    """
    today = today or date.today()
    pending = load_pending()
    executed_count = 0

    credit_group: dict[tuple[str, str], float] = {}
    credit_ids: dict[tuple[str, str], list[int]] = {}
    other_to_execute = []

    for tx in pending:
        if tx.get("status") != "pending":
            continue

        try:
            due = date.fromisoformat(tx.get("date_due", ""))
        except ValueError:
            continue

        if due > today:
            continue

        account_value = str(tx.get("account", "")).strip().lower()
        credit_account_key = _credit_pending_key(account_value) or _credit_pending_key(tx.get("account_key", ""))
        is_credit_payment = bool(credit_account_key) or tx.get("source") == CREDIT_STATEMENT_SOURCE

        if credit_only and not is_credit_payment:
            continue

        try:
            amount = float(tx.get("amount", 0.0))
        except (TypeError, ValueError):
            amount = 0.0

        if tx.get("source") == CREDIT_STATEMENT_SOURCE:
            _execute_pending_row(tx)
            mark_executed(int(tx["id"]))
            executed_count += 1
        elif is_credit_payment:
            group_key = (
                tx["date_due"],
                credit_account_key,
            )
            credit_group[group_key] = credit_group.get(group_key, 0.0) + amount
            credit_ids.setdefault(group_key, []).append(int(tx["id"]))
        else:
            other_to_execute.append(tx)

    if not credit_only:
        for tx in other_to_execute:
            _execute_pending_row(tx)
            mark_executed(int(tx["id"]))
            executed_count += 1

    for (due_date, account_value), total in credit_group.items():
        label = _credit_pending_label(account_value)

        append_transaction({
            "type": "expense",
            "date": due_date,
            "category": CREDIT_CARD_PAYMENT_CATEGORY,
            "sub_category": label,
            "amount": total,
            "account": _credit_execution_account_value(account_value),
            "description": f"{label} payment ({due_date})",
        })

        for tx_id in credit_ids.get((due_date, account_value), []):
            mark_executed(tx_id)
            executed_count += 1

    return executed_count


def sync_credit_account_statements(today: date | None = None) -> int:
    """Create one pending statement row per credit account and closed month.

    Purchases paid with a configured credit account are saved as normal
    transaction rows on the real purchase date, but they do not affect the main
    net. This function aggregates those purchases by calendar month and credit
    account, then creates one pending settlement due on that account's configured
    due day in the following month.

    Example: Visa due day 15, purchases in June => one pending statement due
    July 15. Purchases from July 1-14 are part of July and therefore settle on
    August 15, not July 15.
    """
    today = today or date.today()
    first_day_this_month = date(today.year, today.month, 1)

    try:
        from money_manager.repositories.transactions import load_all
    except Exception:
        return 0

    df = load_all()
    groups: dict[tuple[str, str], dict] = {}
    if not df.empty:
        for _, row in df.iterrows():
            tx_type = str(row.get("type", "")).casefold()
            if tx_type != "expense":
                continue
            key = str(row.get("account_key") or normalize_account_key(row.get("account", "")))
            if account_policy_for_key(key) != MAIN_NET_CREDIT_PENDING:
                continue
            if _is_credit_settlement_transaction_row(row):
                continue
            charge_date = row.get("date")
            if pd.isna(charge_date):
                continue
            if not isinstance(charge_date, pd.Timestamp):
                charge_date = pd.to_datetime(charge_date, errors="coerce")
            if pd.isna(charge_date):
                continue
            charge_day = charge_date.date()
            if charge_day >= first_day_this_month:
                # Current-month charges are not a closed statement yet.
                continue
            statement_month = charge_day.strftime("%Y-%m")
            due_day = _charge_due_day(row, key)
            due = _statement_due_date(charge_day, due_day)
            amount = _safe_float(row.get("amount", 0.0))
            group_key = (key, statement_month, due_day)
            item = groups.setdefault(group_key, {
                "account_key": key,
                "account_label": account_label_for_key(key),
                "statement_month": statement_month,
                "due_day": due_day,
                "date_due": due,
                "amount": 0.0,
                "count": 0,
            })
            item["amount"] += amount
            item["count"] += 1

    rows = load_pending()
    wanted_ids = {f"{item['account_key']}:{item['statement_month']}:due{item.get('due_day', 15)}" for item in groups.values() if item["amount"] > 0.005}
    changed = False

    # Drop stale open credit-statement rows. Executed history is preserved.
    retained: list[dict] = []
    for row in rows:
        if row.get("source") == CREDIT_STATEMENT_SOURCE and row.get("status") == "pending" and row.get("source_id") not in wanted_ids:
            changed = True
            continue
        retained.append(row)
    rows = retained

    by_source_id = {
        row.get("source_id", ""): row
        for row in rows
        if row.get("source") == CREDIT_STATEMENT_SOURCE
    }

    for item in groups.values():
        if item["amount"] <= 0.005:
            continue
        source_id = f"{item['account_key']}:{item['statement_month']}:due{item.get('due_day', 15)}"
        existing = by_source_id.get(source_id)
        payload = {
            "type": "expense",
            "date_due": item["date_due"].isoformat(),
            "amount": f"{item['amount']:.2f}",
            "category": CREDIT_CARD_PAYMENT_CATEGORY,
            "account": item["account_key"],
            "description": f"{item['account_label']} statement {item['statement_month']} due day {item.get('due_day', 15)} ({item['count']} transactions)",
            "status": "pending",
            "source": CREDIT_STATEMENT_SOURCE,
            "source_id": source_id,
            "pending_kind": CREDIT_STATEMENT_KIND,
            "account_key": item["account_key"],
            "account_label": item["account_label"],
            "statement_month": item["statement_month"],
        }
        if existing:
            if existing.get("status") == "pending":
                # Do not rewrite an already-created credit statement due date.
                # This makes due-day edits apply to future statement rows only,
                # instead of moving old/open statements after the fact.
                locked_fields = {"date_due", "source_id", "statement_month"}
                for key, value in payload.items():
                    if key in locked_fields:
                        continue
                    if existing.get(key) != value:
                        existing[key] = value
                        changed = True
        else:
            payload["id"] = _next_pending_id(rows)
            rows.append(payload)
            changed = True

    if changed:
        write_pending(rows)

    # Prompt 11E bridge: build durable credit_settlements.csv rows from the
    # ledger and mirror them into the Pending page without double-executing the
    # legacy credit_account_statement rows above.
    try:
        from money_manager.services.credit_settlement_service import sync_credit_settlements

        sync_credit_settlements(today=today, sync_pending=True)
    except Exception:
        pass
    return len(groups)


def _execute_pending_row(tx: dict, execution_date: str | None = None) -> None:
    execution_date = execution_date or tx.get("date_due", date.today().isoformat())
    account_value = str(tx.get("account", "")).strip().lower()

    if tx.get("source") == "debt":
        from money_manager.services.debt_service import register_pending_debt_payment

        debt_tx = dict(tx)
        debt_tx["date_due"] = execution_date
        register_pending_debt_payment(debt_tx)
        return

    if tx.get("source") == CREDIT_STATEMENT_SOURCE:
        key = _credit_pending_key(tx.get("account_key") or tx.get("account"))
        label = _credit_pending_label(key)
        month = str(tx.get("statement_month") or "").strip()
        append_transaction({
            "type": "expense",
            "date": execution_date,
            "category": CREDIT_CARD_PAYMENT_CATEGORY,
            "sub_category": label,
            "amount": float(tx.get("amount", 0.0)),
            "account": key or tx.get("account", ""),
            "description": f"{label} statement payment {month} ({execution_date})".strip(),
        })
        return

    credit_account_key = _credit_pending_key(account_value) or _credit_pending_key(tx.get("account_key", ""))
    if credit_account_key:
        label = _credit_pending_label(credit_account_key)
        append_transaction({
            "type": "expense",
            "date": execution_date,
            "category": CREDIT_CARD_PAYMENT_CATEGORY,
            "sub_category": label,
            "amount": float(tx.get("amount", 0.0)),
            "account": _credit_execution_account_value(credit_account_key),
            "description": f"{label} payment ({execution_date})",
        })
        return

    account_id = tx.get("account_id") or tx.get("account_key") or tx.get("account", "")
    payment_method_id = tx.get("payment_method_id", "")
    save_transaction_payload(
        {
            "type": tx.get("type", "expense"),
            "date": execution_date,
            "category": tx.get("category", ""),
            "sub_category": tx.get("sub_category", ""),
            "amount": float(tx.get("amount", 0.0)),
            "account": tx.get("account", ""),
            "account_id": account_id,
            "payment_method_id": payment_method_id,
            "description": tx.get("description", ""),
        },
        account_id=account_id,
        payment_method_id=payment_method_id,
    )


def _is_separate_auxiliary_pending(account_value: str | None) -> bool:
    if not is_auxiliary_account(account_value):
        return False
    key = normalize_account_key(account_value)
    return account_policy_for_key(key) == MAIN_NET_SEPARATE


def _credit_pending_key(account_value: str | None) -> str:
    value = str(account_value or "").strip().casefold()
    if value in PAYPAL_CREDIT_ALIASES:
        return PAYPAL_CREDIT_ACCOUNT_VALUE
    key = normalize_account_key(value)
    if account_policy_for_key(key) == MAIN_NET_CREDIT_PENDING:
        return key
    if value in CREDIT_ACCOUNT_KEYWORDS:
        return "credit_card"
    return ""


def _credit_pending_label(account_value: str | None) -> str:
    key = _credit_pending_key(account_value) or str(account_value or "").strip().casefold()
    if key == PAYPAL_CREDIT_ACCOUNT_VALUE or key in PAYPAL_CREDIT_ALIASES:
        return "PayPal credit route"
    return account_label_for_key(key)


def _credit_execution_account_value(account_value: str | None) -> str:
    key = _credit_pending_key(account_value) or str(account_value or "").strip().casefold()
    if key == PAYPAL_CREDIT_ACCOUNT_VALUE or key in PAYPAL_CREDIT_ALIASES:
        return PAYPAL_CREDIT_ACCOUNT_VALUE
    # Store stable account key for configured credit accounts.
    return normalize_account_key(key)


def _decorate_pending_row(row: dict) -> dict:
    decorated = dict(row)
    decorated["status"] = str(decorated.get("status", "pending") or "pending").lower()
    decorated["type"] = str(decorated.get("type", "expense") or "expense").lower()
    decorated["account_label"] = decorated.get("account_label") or account_label_for_value(decorated.get("account", ""))
    decorated["is_credit_statement"] = decorated.get("source") == CREDIT_STATEMENT_SOURCE or decorated.get("pending_kind") == CREDIT_STATEMENT_KIND
    credit_key = _credit_pending_key(decorated.get("account_key") or decorated.get("account", ""))
    decorated["is_auxiliary_account"] = (
        is_auxiliary_account(decorated.get("account", ""))
        and not decorated["is_credit_statement"]
        and account_policy_for_key(normalize_account_key(decorated.get("account", ""))) == MAIN_NET_SEPARATE
        and not credit_key
    )
    decorated["statement_month"] = str(decorated.get("statement_month", "") or "")

    try:
        amount = float(decorated.get("amount", 0.0))
    except (TypeError, ValueError):
        amount = 0.0
    decorated["amount_value"] = amount
    decorated["amount_str"] = f"€ {amount:.2f}"
    decorated["direction_label"] = "Expected income" if decorated["type"] == "income" else "Expected outflow"
    decorated["impact_tone"] = "income" if decorated["type"] == "income" else "expense"

    try:
        due = date.fromisoformat(decorated.get("date_due", ""))
    except ValueError:
        due = date.max
    decorated["date_due_sort"] = due
    decorated["date_due_str"] = "" if due == date.max else due.isoformat()

    if due == date.max:
        delay_base = date.today()
    else:
        delay_base = max(due, date.today())
    decorated["delay_date_default"] = (delay_base + timedelta(days=1)).isoformat()
    decorated["is_overdue"] = bool(due != date.max and due < date.today() and decorated["status"] == "pending")
    decorated["is_due_today"] = bool(due == date.today() and decorated["status"] == "pending")

    if decorated["is_credit_statement"]:
        decorated["credit_charge_details"] = _credit_statement_charge_details(
            decorated.get("account_key") or decorated.get("account"),
            decorated.get("statement_month"),
        )
        decorated["credit_charge_count"] = len(decorated["credit_charge_details"])
    else:
        decorated["credit_charge_details"] = []
        decorated["credit_charge_count"] = 0
    return decorated


def _statement_due_date(charge_day: date, due_day: int) -> date:
    due_day = max(1, min(31, int(due_day or 15)))
    if charge_day.month == 12:
        year, month = charge_day.year + 1, 1
    else:
        year, month = charge_day.year, charge_day.month + 1
    # Clamp 31 to shorter months.
    while True:
        try:
            return date(year, month, due_day)
        except ValueError:
            due_day -= 1


def _is_credit_settlement_transaction_row(row) -> bool:
    description = str(row.get("description", "") or "").strip().casefold()
    sub_category = str(row.get("sub_category", "") or "").strip().casefold()
    account = str(row.get("account", "") or "").strip().casefold()
    text = f"{description} {sub_category}"
    explicit_statement_payment = (
        "statement payment" in text
        or "credit card payment" in text
        or "credit statement payment" in text
        or "settlement" in text
    )
    legacy_paypal_payment = account in PAYPAL_CREDIT_ALIASES and "payment" in text
    return explicit_statement_payment or legacy_paypal_payment


def _charge_due_day(row, account_key: str) -> int:
    snapshot = _safe_int(row.get("account_due_day_snapshot"))
    if snapshot and 1 <= snapshot <= 31:
        return snapshot
    return account_due_day_for_key(account_key, 15)


def _safe_int(value, default: int | None = None) -> int | None:
    try:
        return int(str(value or "").strip())
    except (TypeError, ValueError):
        return default


def _credit_statement_charge_details(account_value: str | None, statement_month: str | None) -> list[dict]:
    key = _credit_pending_key(account_value) or normalize_account_key(account_value)
    statement_month = str(statement_month or "").strip()
    if not key or not statement_month:
        return []
    try:
        from money_manager.repositories.transactions import load_all
    except Exception:
        return []
    df = load_all()
    if df.empty:
        return []
    details: list[dict] = []
    for _, row in df.iterrows():
        if str(row.get("type", "")).casefold() != "expense":
            continue
        if str(row.get("account_key") or "") != key:
            continue
        if _is_credit_settlement_transaction_row(row):
            continue
        tx_date = row.get("date")
        if pd.isna(tx_date):
            continue
        if not isinstance(tx_date, pd.Timestamp):
            tx_date = pd.to_datetime(tx_date, errors="coerce")
        if pd.isna(tx_date) or tx_date.strftime("%Y-%m") != statement_month:
            continue
        amount = _safe_float(row.get("amount", 0.0))
        details.append({
            "date": tx_date.strftime("%Y-%m-%d"),
            "category": row.get("category", ""),
            "description": row.get("description", ""),
            "amount": amount,
            "amount_str": f"€ {amount:.2f}",
        })
    return sorted(details, key=lambda item: item["date"])


def _next_pending_id(rows: list[dict]) -> int:
    ids = [int(row.get("id", 0)) for row in rows if str(row.get("id", "")).isdigit()]
    return max(ids, default=0) + 1


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return default

# --- Scoped planning compatibility wrappers (Prompt 15B) ---
def pending_rows_for_scope(rows: list[dict], scope, user_id: str | None = None) -> list[dict]:
    from money_manager.services.account_scope_service import pending_rows_for_scope as _scoped_rows

    return _scoped_rows(rows, scope, user_id=user_id)


def pending_total_for_scope(scope, user_id: str | None = None) -> float:
    from money_manager.services.account_scope_service import pending_total_for_scope as _scoped_total

    return float(_scoped_total(scope, user_id=user_id))


def pending_context_for_scope(scope, user_id: str | None = None) -> dict:
    from money_manager.services.account_scope_service import pending_context_for_scope as _scoped_context

    return _scoped_context(scope, user_id=user_id)
