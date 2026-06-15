from datetime import date

from money_manager.config import CREDIT_ACCOUNT_KEYWORDS, CREDIT_CARD_DUE_DAY, account_label_for_value, is_auxiliary_account

from money_manager.repositories.pending import append_pending, delete_pending_for_source, load_pending
from money_manager.repositories.recurring import (
    add_months,
    append_recurring,
    delete_recurring,
    first_due_date,
    load_recurring,
    normalize_amount,
    parse_date,
    parse_frequency_months,
    update_recurring,
    write_recurring,
)



def prepare_recurring_for_display(rows: list[dict]) -> list[dict]:
    """Decorate recurring rules with UI-only fields and sort by next due date."""
    prepared = []
    for row in rows:
        decorated = dict(row)

        try:
            amount = float(decorated.get("amount", 0.0))
        except (TypeError, ValueError):
            amount = 0.0

        frequency = parse_frequency_months(decorated.get("frequency"))
        next_due = next_due_date_for_rule(decorated)

        decorated["type"] = str(decorated.get("type", "expense") or "expense").lower()
        decorated["amount_value"] = amount
        decorated["amount_str"] = f"€ {amount:.2f}"
        decorated["frequency"] = frequency
        decorated["monthly_equivalent"] = amount / frequency if frequency else amount
        decorated["annual_equivalent"] = decorated["monthly_equivalent"] * 12
        decorated["frequency_label"] = "Monthly" if frequency == 1 else f"Every {frequency} months"
        decorated["next_payment"] = next_due.isoformat()
        decorated["next_payment_sort"] = next_due
        decorated["start_date"] = decorated.get("start_date", "") or "—"
        decorated["account_label"] = account_label_for_value(decorated.get("account", ""))
        decorated["is_auxiliary_account"] = is_auxiliary_account(decorated.get("account", ""))
        prepared.append(decorated)

    return sorted(prepared, key=lambda row: (row["next_payment_sort"], row.get("name", "")))

def append_rule_from_form(form) -> None:
    append_recurring({
        "name": form.get("name", ""),
        "type": form.get("type", "expense"),
        "amount": float(form.get("amount", 0)),
        "frequency": int(form.get("frequency", 1)),
        "day_of_month": int(form.get("day_of_month", 1)),
        "category": form.get("category", ""),
        "account": form.get("account", "auto"),
        "start_date": form.get("start_date", ""),
    })


def update_rule_from_form(form) -> None:
    rule_id = form.get("id")
    delete_pending_for_source("recurring", rule_id, only_pending=True)
    update_recurring(
        rule_id,
        {
            "name": form.get("name", ""),
            "type": form.get("type", "expense"),
            "amount": float(form.get("amount", 0)),
            "frequency": int(form.get("frequency", 1)),
            "day_of_month": int(form.get("day_of_month", 1)),
            "category": form.get("category", ""),
            "account": form.get("account", "auto"),
            "start_date": form.get("start_date", ""),
        },
    )


def delete_rule_from_form(form) -> None:
    rule_id = form.get("id")
    delete_pending_for_source("recurring", rule_id, only_pending=True)
    delete_recurring(int(rule_id))


def next_due_date_for_rule(row: dict, today: date | None = None) -> date:
    today = today or date.today()
    frequency_months = parse_frequency_months(row.get("frequency"))

    try:
        desired_day = int(row.get("day_of_month", 1))
    except (TypeError, ValueError):
        desired_day = 1

    last_generated = parse_date(row.get("last_generated"))

    if last_generated:
        return add_months(last_generated, frequency_months, desired_day)

    return first_due_date(row, today)


def _is_credit_style_recurring(row: dict) -> bool:
    account = str(row.get("account", "")).strip().lower()
    tx_type = str(row.get("type", "expense")).strip().lower()

    return tx_type == "expense" and account in {
        *CREDIT_ACCOUNT_KEYWORDS,
        "paypal",
        "pay pal",
        "paypal_credit",
        "paypal credit",
        "pay pal credit",
    }


def _credit_due_date_from_charge_date(charge_date: date) -> date:
    """Credit-card style settlement: charge this month, pay next month."""
    if charge_date.month == 12:
        return date(charge_date.year + 1, 1, CREDIT_CARD_DUE_DAY)

    return date(charge_date.year, charge_date.month + 1, CREDIT_CARD_DUE_DAY)


def _pending_due_date_for_rule(row: dict, scheduled_date: date) -> date:
    if _is_credit_style_recurring(row):
        return _credit_due_date_from_charge_date(scheduled_date)

    return scheduled_date


def _pending_account_for_rule(row: dict) -> str:
    account = str(row.get("account", "auto")).strip().lower()

    if account in {"paypal", "pay pal", "paypal_credit", "paypal credit", "pay pal credit"}:
        return "paypal_credit"

    if _is_credit_style_recurring(row):
        return "credit"

    return row.get("account", "auto")


def generate_recurring(today: date | None = None) -> int:
    today = today or date.today()
    rows = load_recurring()

    changed = False
    created = 0

    for row in rows:
        for scheduled_date in _iter_due_dates_to_generate(row, today):
            pending_due_date = _pending_due_date_for_rule(row, scheduled_date)

            if _matching_pending_exists(row, scheduled_date):
                row["last_generated"] = scheduled_date.isoformat()
                changed = True
                continue

            append_pending(
                {
                    "type": row.get("type", "expense"),
                    "amount": normalize_amount(row.get("amount", 0)),
                    "category": row.get("category", ""),
                    "account": _pending_account_for_rule(row),
                    "description": row.get("name", ""),
                    "source": "recurring",
                    "source_id": row.get("id", ""),
                },
                pending_due_date,
            )

            row["last_generated"] = scheduled_date.isoformat()
            changed = True
            created += 1

    if changed:
        write_recurring(rows)

    return created


def _iter_due_dates_to_generate(row: dict, today: date):
    frequency_months = parse_frequency_months(row.get("frequency"))

    try:
        desired_day = int(row.get("day_of_month", 1))
    except (TypeError, ValueError):
        desired_day = 1

    due_date = first_due_date(row, today)
    last_generated = parse_date(row.get("last_generated"))

    if last_generated:
        while due_date <= last_generated:
            due_date = add_months(due_date, frequency_months, desired_day)

    while due_date <= today:
        yield due_date
        due_date = add_months(due_date, frequency_months, desired_day)


def _matching_pending_exists(row: dict, scheduled_date: date) -> bool:
    pending_due_date = _pending_due_date_for_rule(row, scheduled_date)
    due = pending_due_date.isoformat()

    name = str(row.get("name", ""))
    transaction_type = str(row.get("type", ""))
    category = str(row.get("category", ""))
    account = str(_pending_account_for_rule(row))
    amount = normalize_amount(row.get("amount", 0))

    for tx in load_pending():
        if tx.get("date_due") != due:
            continue
        if tx.get("description") != name:
            continue
        if tx.get("type") != transaction_type:
            continue
        if tx.get("category") != category:
            continue
        if str(tx.get("account", "auto")) != account:
            continue

        if abs(normalize_amount(tx.get("amount", 0)) - amount) < 0.01:
            return True

    return False
