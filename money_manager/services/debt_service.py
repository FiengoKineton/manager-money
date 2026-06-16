from datetime import date, datetime

from money_manager.config import DEBT_PAYMENT_CATEGORY
from money_manager.repositories.debts import (
    append_debt,
    append_debt_rule,
    delete_debt,
    delete_debt_rule,
    load_debt_rules,
    load_debts,
    update_debt,
    update_debt_rule,
    write_debt_rules,
)
from money_manager.repositories.pending import append_pending, delete_pending_for_source, delete_pending_for_source_description, load_pending
from money_manager.repositories.recurring import add_months, first_due_date, normalize_amount, parse_date, parse_frequency_months
from money_manager.repositories.transactions import append_transaction


def add_debt_from_form(form) -> None:
    amount = _amount(form.get("original_amount"))
    append_debt({
        "name": form.get("name", ""),
        "creditor": form.get("creditor", ""),
        "original_amount": amount,
        "remaining_amount": _amount(form.get("remaining_amount", amount)) or amount,
        "category": DEBT_PAYMENT_CATEGORY,
        "account": form.get("account", ""),
        "start_date": form.get("start_date", date.today().isoformat()),
        "due_date": form.get("due_date", ""),
        "description": form.get("description", ""),
    })


def delete_debt_from_form(form) -> None:
    try:
        debt_id = int(form.get("id"))
    except (TypeError, ValueError):
        return
    delete_pending_for_source("debt", debt_id, only_pending=True)
    delete_debt(debt_id)


def update_debt_from_form(form) -> None:
    debt_id = _safe_int(form.get("id"))
    if debt_id is None:
        return

    remaining = _amount(form.get("remaining_amount"))
    status = form.get("status", "active")
    if remaining <= 0.005:
        status = "paid"

    updates = {
        "name": form.get("name", ""),
        "creditor": form.get("creditor", ""),
        "original_amount": _amount(form.get("original_amount")),
        "remaining_amount": remaining,
        "account": form.get("account", ""),
        "start_date": form.get("start_date", ""),
        "due_date": form.get("due_date", ""),
        "description": form.get("description", ""),
        "status": status,
    }
    if status != "active":
        updates["closed_at"] = datetime.now().isoformat(timespec="seconds")
    update_debt(debt_id, updates)

    if status != "active":
        _deactivate_rules_for_debt(debt_id)
        delete_pending_for_source("debt", debt_id, only_pending=True)


def pay_debt_from_form(form) -> None:
    debt_id = _safe_int(form.get("id"))
    if debt_id is None:
        return

    amount = _amount(form.get("amount"))
    if amount <= 0:
        debt = debt_by_id(debt_id)
        amount = _amount(debt.get("remaining_amount")) if debt else 0.0

    register_debt_payment(
        debt_id=debt_id,
        amount=amount,
        payment_date=form.get("date", date.today().isoformat()),
        account=form.get("account", ""),
        description=form.get("description", ""),
    )

def pay_creditor_debts_from_form(form) -> None:
    creditor = str(form.get("creditor", "")).strip()
    if not creditor:
        return

    payment_date = form.get("date", date.today().isoformat())
    account = form.get("account", "")
    description = form.get("description", "")

    active_debts = [
        debt for debt in load_debts()
        if debt.get("status") == "active"
        and _amount(debt.get("remaining_amount")) > 0
        and str(debt.get("creditor", "")).strip().lower() == creditor.lower()
    ]

    for debt in active_debts:
        remaining = _amount(debt.get("remaining_amount"))

        register_debt_payment(
            debt_id=debt.get("id"),
            amount=remaining,
            payment_date=payment_date,
            account=account or debt.get("account", ""),
            description=description or f"Full debt payoff to {creditor}: {debt.get('name', '')}",
        )


def add_rule_from_form(form) -> None:
    debt_id = form.get("debt_id", "")
    debt = debt_by_id(debt_id)

    rule_type = form.get("rule_type", "monthly_instalment")
    if rule_type not in {"monthly_instalment", "payoff_date"}:
        rule_type = "monthly_instalment"

    if rule_type == "payoff_date":
        fallback_name = f"Extinguish - {debt.get('name', '')}" if debt else "Extinguish debt"
        amount = 0.0
    else:
        fallback_name = f"Debt payment - {debt.get('name', '')}" if debt else "Debt payment"
        amount = _amount(form.get("amount"))

    append_debt_rule({
        "debt_id": debt_id,
        "name": form.get("name") or fallback_name,
        "rule_type": rule_type,
        "amount": amount,
        "frequency": form.get("frequency", 1),
        "day_of_month": form.get("day_of_month", 1),
        "start_date": form.get("start_date", date.today().isoformat()),
        "payoff_date": form.get("payoff_date", ""),
    })


def delete_rule_from_form(form) -> None:
    rule_id = _safe_int(form.get("id"))
    if rule_id is None:
        return
    rule = rule_by_id(rule_id)
    if rule:
        delete_pending_for_source_description("debt", rule.get("debt_id", ""), _pending_description(rule), only_pending=True)
    delete_debt_rule(rule_id)


def update_rule_from_form(form) -> None:
    rule_id = _safe_int(form.get("id"))
    if rule_id is None:
        return

    rule_type = form.get("rule_type", "monthly_instalment")
    if rule_type not in {"monthly_instalment", "payoff_date"}:
        rule_type = "monthly_instalment"

    updates = {
        "debt_id": form.get("debt_id", ""),
        "name": form.get("name", ""),
        "rule_type": rule_type,
        "amount": 0.0 if rule_type == "payoff_date" else _amount(form.get("amount")),
        "frequency": form.get("frequency", 1),
        "day_of_month": form.get("day_of_month", 1),
        "start_date": form.get("start_date", ""),
        "payoff_date": form.get("payoff_date", ""),
        "active": "1" if form.get("active") else "0",
    }
    update_debt_rule(rule_id, updates)
    _sync_debt_rules_with_debts()


def pay_rule_now_from_form(form) -> None:
    rule_id = _safe_int(form.get("id"))
    if rule_id is None:
        return

    rule = rule_by_id(rule_id)
    if not rule:
        return

    debt = debt_by_id(rule.get("debt_id"))
    if not debt:
        return

    if rule.get("rule_type") == "payoff_date":
        amount = _amount(debt.get("remaining_amount"))
        description = f"Manual debt extinguishment: {rule.get('name', '')}"
        updates = {
            "last_generated": date.today().isoformat(),
            "active": "0",
        }
    else:
        amount = normalize_amount(rule.get("amount"))
        description = f"Manual debt instalment: {rule.get('name', '')}"
        updates = {
            "last_generated": date.today().isoformat(),
        }

    register_debt_payment(
        debt_id=rule.get("debt_id"),
        amount=amount,
        payment_date=date.today().isoformat(),
        account="manual",
        description=description,
    )

    update_debt_rule(rule_id, updates)


def register_debt_payment(debt_id, amount: float, payment_date: str, account: str = "", description: str = "") -> None:
    debt = debt_by_id(debt_id)
    if not debt:
        return

    amount = min(_amount(amount), _amount(debt.get("remaining_amount")))
    if amount <= 0:
        return

    append_transaction({
        "type": "expense",
        "date": payment_date or date.today().isoformat(),
        "category": DEBT_PAYMENT_CATEGORY,
        "sub_category": debt.get("name", ""),
        "amount": amount,
        "account": account or debt.get("account", ""),
        "description": description or f"Debt payment to {debt.get('creditor', '')}: {debt.get('name', '')}",
    })

    remaining = max(0.0, _amount(debt.get("remaining_amount")) - amount)
    updates = {"remaining_amount": remaining}
    if remaining <= 0.005:
        updates["status"] = "paid"
        updates["closed_at"] = datetime.now().isoformat(timespec="seconds")
    update_debt(int(debt["id"]), updates)

    if remaining <= 0.005:
        _deactivate_rules_for_debt(debt_id)
        delete_pending_for_source("debt", debt_id, only_pending=True)


def generate_debt_payments(today: date | None = None) -> int:
    today = today or date.today()
    rows = load_debt_rules()
    changed = False
    created = 0

    debt_lookup = {str(debt.get("id")): debt for debt in load_debts()}

    for row in rows:
        if str(row.get("active", "1")) not in {"1", "true", "True", "yes"}:
            continue

        debt = debt_lookup.get(str(row.get("debt_id")))
        remaining_budget = _amount(debt.get("remaining_amount")) if debt else 0.0

        if not debt or debt.get("status") != "active" or remaining_budget <= 0:
            row["active"] = "0"
            changed = True
            continue

        rule_type = row.get("rule_type", "monthly_instalment")

        if rule_type == "payoff_date":
            payoff_date = parse_date(row.get("payoff_date"))

            if not payoff_date:
                continue

            if payoff_date > today:
                continue

            if _matching_pending_exists(row, payoff_date):
                row["last_generated"] = payoff_date.isoformat()
                row["active"] = "0"
                changed = True
                continue

            append_pending({
                "type": "expense",
                "amount": remaining_budget,
                "category": DEBT_PAYMENT_CATEGORY,
                "account": "auto",
                "description": _pending_description(row),
                "source": "debt",
                "source_id": row.get("debt_id", ""),
            }, payoff_date)

            row["last_generated"] = payoff_date.isoformat()
            row["active"] = "0"
            changed = True
            created += 1
            continue

        for due_date in _iter_due_dates_to_generate(row, today):
            amount = min(normalize_amount(row.get("amount")), remaining_budget)

            if amount <= 0:
                break

            if _matching_pending_exists(row, due_date):
                remaining_budget = max(0.0, remaining_budget - amount)
                row["last_generated"] = due_date.isoformat()
                changed = True
                continue

            append_pending({
                "type": "expense",
                "amount": amount,
                "category": DEBT_PAYMENT_CATEGORY,
                "account": "auto",
                "description": _pending_description(row),
                "source": "debt",
                "source_id": row.get("debt_id", ""),
            }, due_date)

            remaining_budget = max(0.0, remaining_budget - amount)
            row["last_generated"] = due_date.isoformat()
            changed = True
            created += 1

    if changed:
        write_debt_rules(rows)

    return created


def register_pending_debt_payment(tx: dict) -> None:
    debt_id = tx.get("source_id")
    register_debt_payment(
        debt_id=debt_id,
        amount=normalize_amount(tx.get("amount", 0)),
        payment_date=tx.get("date_due", date.today().isoformat()),
        account=tx.get("account", "auto"),
        description=tx.get("description", ""),
    )


def debt_by_id(debt_id) -> dict | None:
    for debt in load_debts():
        if str(debt.get("id")) == str(debt_id):
            return debt
    return None


def rule_by_id(rule_id) -> dict | None:
    for rule in load_debt_rules():
        if str(rule.get("id")) == str(rule_id):
            return rule
    return None


def page_context() -> dict:
    _sync_debt_rules_with_debts()
    generate_debt_payments()

    debts = load_debts()
    rules = load_debt_rules()
    pending = [tx for tx in load_pending() if tx.get("source") == "debt" and tx.get("status") == "pending"]
    debt_lookup = {str(row.get("id")): row for row in debts}

    for debt in debts:
        original = _amount(debt.get("original_amount"))
        remaining = _amount(debt.get("remaining_amount"))
        debt["original_amount"] = original
        debt["remaining_amount"] = remaining
        debt["paid_amount"] = max(0.0, original - remaining)
        debt["progress"] = 0.0 if original <= 0 else min(100.0, debt["paid_amount"] / original * 100.0)

    for rule in rules:
        rule["amount"] = _amount(rule.get("amount"))
        rule["frequency"] = _safe_int(rule.get("frequency")) or 1
        linked_debt = debt_lookup.get(str(rule.get("debt_id")), {})
        linked_remaining = _amount(linked_debt.get("remaining_amount")) if linked_debt else 0.0
        rule["debt_name"] = linked_debt.get("name", "Unknown debt")
        rule["debt_remaining"] = linked_remaining
        rule["linked_debt_active"] = bool(linked_debt and linked_debt.get("status") == "active" and linked_remaining > 0)
        rule["is_active"] = str(rule.get("active", "1")).strip().lower() in {"1", "true", "yes", "on"}

        if rule.get("rule_type") == "payoff_date":
            rule["rule_type_label"] = "Extinguish on date"
            rule["amount_label"] = "Remaining balance"
            rule["frequency_label"] = "One time"
        else:
            rule["rule_type_label"] = "Monthly instalment"
            rule["amount_label"] = f"{rule['amount']:.2f}"
            rule["frequency_label"] = f"Every {rule['frequency']} month(s)"

        next_due = next_due_date_for_rule(rule)
        rule["next_payment"] = next_due.isoformat() if next_due else ""
        rule["is_payable"] = bool(rule["is_active"] and rule["linked_debt_active"] and next_due)
        rule["status_label"] = "Active" if rule["is_payable"] else "Completed / inactive"

    active_debts = [row for row in debts if row.get("status") == "active" and _amount(row.get("remaining_amount")) > 0]
    creditor_summaries = creditor_summaries_from_debts(active_debts)

    totals = {
        "active_remaining": sum(_amount(row.get("remaining_amount")) for row in active_debts),
        "original_active": sum(_amount(row.get("original_amount")) for row in active_debts),
        "paid_tracked": sum(_amount(row.get("original_amount")) - _amount(row.get("remaining_amount")) for row in debts),
        "pending_debt_payments": sum(_amount(row.get("amount")) for row in pending),
    }

    return {
        "debts": debts,
        "active_debts": active_debts,
        "debt_options": debts,
        "rules": rules,
        "pending_debt_payments": pending,
        "totals": totals,
        "today": date.today().isoformat(),
        "creditor_summaries": creditor_summaries,
    }


def next_due_date_for_rule(row: dict, today: date | None = None) -> date | None:
    today = today or date.today()

    if str(row.get("active", "1")).strip().lower() not in {"1", "true", "yes", "on"}:
        return None

    if row.get("rule_type") == "payoff_date":
        if str(row.get("active", "1")) not in {"1", "true", "True", "yes"}:
            return None
        return parse_date(row.get("payoff_date"))

    frequency_months = parse_frequency_months(row.get("frequency"))
    desired_day = _safe_int(row.get("day_of_month")) or 1
    last_generated = parse_date(row.get("last_generated"))

    if last_generated:
        return add_months(last_generated, frequency_months, desired_day)

    return first_due_date({
        "start_date": row.get("start_date"),
        "day_of_month": row.get("day_of_month", 1),
    }, today)


def _iter_due_dates_to_generate(row: dict, today: date):
    frequency_months = parse_frequency_months(row.get("frequency"))
    desired_day = _safe_int(row.get("day_of_month")) or 1
    due_date = first_due_date({
        "start_date": row.get("start_date"),
        "day_of_month": row.get("day_of_month", 1),
    }, today)
    last_generated = parse_date(row.get("last_generated"))

    if last_generated:
        while due_date <= last_generated:
            due_date = add_months(due_date, frequency_months, desired_day)

    while due_date <= today:
        yield due_date
        due_date = add_months(due_date, frequency_months, desired_day)


def _matching_pending_exists(row: dict, due_date: date) -> bool:
    due = due_date.isoformat()
    expected_description = _pending_description(row)

    for tx in load_pending():
        if tx.get("date_due") != due:
            continue
        if tx.get("source") != "debt":
            continue
        if str(tx.get("source_id")) != str(row.get("debt_id")):
            continue
        if tx.get("description") != expected_description:
            continue
        if tx.get("status") == "pending":
            return True

    return False

def _pending_description(row: dict) -> str:
    if row.get("rule_type") == "payoff_date":
        return f"Debt extinguishment: {row.get('name', '')}"

    return f"Debt instalment: {row.get('name', '')}"


def _deactivate_rules_for_debt(debt_id) -> None:
    rows = load_debt_rules()
    changed = False
    for row in rows:
        if str(row.get("debt_id")) == str(debt_id) and str(row.get("active", "1")) != "0":
            row["active"] = "0"
            changed = True
    if changed:
        write_debt_rules(rows)


def _sync_debt_rules_with_debts() -> None:
    debts = {str(row.get("id")): row for row in load_debts()}
    rows = load_debt_rules()
    changed = False
    for row in rows:
        debt = debts.get(str(row.get("debt_id")))
        if not debt or debt.get("status") != "active" or _amount(debt.get("remaining_amount")) <= 0:
            if str(row.get("active", "1")) != "0":
                row["active"] = "0"
                changed = True
    if changed:
        write_debt_rules(rows)


def _safe_int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None

def creditor_summaries_from_debts(debts: list[dict]) -> list[dict]:
    grouped = {}

    for debt in debts:
        if debt.get("status") != "active":
            continue

        remaining = _amount(debt.get("remaining_amount"))
        if remaining <= 0:
            continue

        creditor = str(debt.get("creditor", "")).strip() or "Unknown creditor"

        if creditor not in grouped:
            grouped[creditor] = {
                "creditor": creditor,
                "total_remaining": 0.0,
                "debt_count": 0,
                "debts": [],
            }

        grouped[creditor]["total_remaining"] += remaining
        grouped[creditor]["debt_count"] += 1
        grouped[creditor]["debts"].append(debt)

    return sorted(
        grouped.values(),
        key=lambda row: row["total_remaining"],
        reverse=True,
    )

def _amount(value) -> float:
    try:
        return max(0.0, float(str(value or 0).replace(",", ".")))
    except (TypeError, ValueError):
        return 0.0
