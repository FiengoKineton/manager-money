from __future__ import annotations

from datetime import date
import calendar

from money_manager.config import (
    CREDIT_ACCOUNT_KEYWORDS,
    CREDIT_CARD_DUE_DAY,
    MAIN_NET_CREDIT_PENDING,
    PAYPAL_CREDIT_ALIASES,
    PAYPAL_CREDIT_ACCOUNT_VALUE,
    account_due_day_for_key,
    account_label_for_key,
    account_label_for_value,
    account_policy_for_key,
    is_auxiliary_account,
    normalize_account_key,
)

from money_manager.repositories.pending import append_pending, delete_pending_for_source, load_pending
from money_manager.repositories.recurring import (
    add_months,
    append_recurring,
    delete_recurring,
    first_due_date,
    load_recurring,
    normalize_amount,
    occurrence_count_until,
    parse_date,
    parse_frequency_months,
    parse_max_occurrences,
    update_recurring,
    write_recurring,
)


def prepare_recurring_sections(rows: list[dict]) -> dict:
    """Prepare active and finished recurring rules for the Recurring page."""
    prepared = [_decorate_rule(row) for row in rows]
    active = sorted(
        [row for row in prepared if not row["is_finished"]],
        key=lambda row: (row["next_payment_sort"], row.get("name", "")),
    )
    finished = sorted(
        [row for row in prepared if row["is_finished"]],
        key=lambda row: (row["last_generated_sort"], row.get("name", "")),
        reverse=True,
    )

    return {
        "all": [*active, *finished],
        "active": active,
        "finished": finished,
    }


def prepare_recurring_for_display(rows: list[dict]) -> list[dict]:
    """Backward-compatible helper: return only active rules."""
    return prepare_recurring_sections(rows)["active"]


def append_rule_from_form(form) -> None:
    end_date, max_occurrences = _termination_fields_from_form(form)

    append_recurring({
        "name": form.get("name", ""),
        "type": form.get("type", "expense"),
        "amount": float(form.get("amount", 0)),
        "frequency": int(form.get("frequency", 1)),
        "day_of_month": int(form.get("day_of_month", 1)),
        "category": form.get("category", ""),
        "account": form.get("account", "auto"),
        "start_date": form.get("start_date", ""),
        "end_date": end_date,
        "max_occurrences": max_occurrences,
    })


def update_rule_from_form(form) -> None:
    rule_id = form.get("id")
    old_rule = _find_rule_by_id(rule_id)
    pending_rows_before = load_pending()
    has_open_generated_rows = any(
        tx.get("source") == "recurring"
        and str(tx.get("source_id", "")) == str(rule_id)
        and str(tx.get("status", "pending")).lower() == "pending"
        for tx in pending_rows_before
    )

    # Only open generated pending rows are removed. Executed rows stay as
    # historical transactions, so price changes affect the next payments only.
    delete_pending_for_source("recurring", rule_id, only_pending=True)

    end_date, max_occurrences = _termination_fields_from_form(form)

    updates = {
        "name": form.get("name", ""),
        "type": form.get("type", "expense"),
        "amount": float(form.get("amount", 0)),
        "frequency": int(form.get("frequency", 1)),
        "day_of_month": int(form.get("day_of_month", 1)),
        "category": form.get("category", ""),
        "account": form.get("account", "auto"),
        "start_date": form.get("start_date", ""),
        "end_date": end_date,
        "max_occurrences": max_occurrences,
    }

    if old_rule and has_open_generated_rows:
        retained_last = _last_retained_generated_date(old_rule, pending_rows_before)
        updates["last_generated"] = retained_last.isoformat() if retained_last else ""

    update_recurring(rule_id, updates)


def delete_rule_from_form(form) -> None:
    rule_id = form.get("id")
    delete_pending_for_source("recurring", rule_id, only_pending=True)
    delete_recurring(int(rule_id))



def _termination_fields_from_form(form) -> tuple[str, str]:
    """Return mutually-exclusive stop controls from the edit/create form.

    The user can stop a rule either by an exact end date or after N
    occurrences. If both are filled, the occurrence limit wins because it
    depends on the rule frequency, for example 2 quarterly payments means
    July + October, not today + 2 months.
    """
    max_occurrences = str(form.get("max_occurrences", "") or "").strip()
    end_date = str(form.get("end_date", "") or "").strip()

    if max_occurrences:
        end_date = ""

    return end_date, max_occurrences


def _find_rule_by_id(rule_id) -> dict | None:
    for row in load_recurring():
        if str(row.get("id", "")) == str(rule_id):
            return row
    return None


def _last_retained_generated_date(row: dict, pending_rows: list[dict]) -> date | None:
    """Latest scheduled occurrence still backed by a non-pending history row."""
    rule_id = str(row.get("id", ""))
    candidates: list[date] = []

    for tx in pending_rows:
        same_source = tx.get("source") == "recurring" and str(tx.get("source_id", "")) == rule_id
        same_legacy = (
            not tx.get("source")
            and tx.get("description") == row.get("name", "")
            and tx.get("type") == row.get("type", "")
            and tx.get("category") == row.get("category", "")
        )
        if not (same_source or same_legacy):
            continue
        if str(tx.get("status", "pending")).lower() == "pending":
            continue

        due_date = parse_date(tx.get("date_due"))
        if not due_date:
            continue
        candidates.append(_scheduled_date_from_pending_due(row, due_date))

    return max(candidates, default=None)


def _scheduled_date_from_pending_due(row: dict, pending_due_date: date) -> date:
    if not _is_credit_style_recurring(row):
        return pending_due_date

    try:
        desired_day = int(row.get("day_of_month", 1))
    except (TypeError, ValueError):
        desired_day = 1

    return add_months(pending_due_date, -1, desired_day)

def next_due_date_for_rule(row: dict, today: date | None = None) -> date:
    today = today or date.today()
    frequency_months = parse_frequency_months(row.get("frequency"))

    try:
        desired_day = int(row.get("day_of_month", 1))
    except (TypeError, ValueError):
        desired_day = 1

    first_due = first_due_date(row, today)
    last_generated = parse_date(row.get("last_generated"))

    if last_generated:
        candidate = add_months(last_generated, frequency_months, desired_day)
        return max(candidate, first_due)

    return first_due


def is_rule_finished(row: dict, today: date | None = None) -> bool:
    today = today or date.today()
    generated_count = occurrence_count_until(row, parse_date(row.get("last_generated")))
    max_occurrences = parse_max_occurrences(row.get("max_occurrences"))

    if max_occurrences is not None and generated_count >= max_occurrences:
        return True

    end_date = parse_date(row.get("end_date"))
    if end_date and next_due_date_for_rule(row, today) > end_date:
        return True

    return False


def _credit_style_key(account_value: str | None) -> str:
    account = str(account_value or "").strip().casefold()
    if account in PAYPAL_CREDIT_ALIASES:
        return PAYPAL_CREDIT_ACCOUNT_VALUE
    if account in CREDIT_ACCOUNT_KEYWORDS:
        return "credit"
    key = normalize_account_key(account)
    if account_policy_for_key(key) == MAIN_NET_CREDIT_PENDING:
        return key
    return ""


def _is_credit_style_recurring(row: dict) -> bool:
    tx_type = str(row.get("type", "expense")).strip().lower()
    return tx_type == "expense" and bool(_credit_style_key(row.get("account", "")))


def _credit_due_date_from_charge_date(charge_date: date, due_day: int = CREDIT_CARD_DUE_DAY) -> date:
    """Credit-style settlement: charge this month, pay next month."""
    if charge_date.month == 12:
        return date(charge_date.year + 1, 1, due_day)

    return date(charge_date.year, charge_date.month + 1, due_day)


def _pending_due_date_for_rule(row: dict, scheduled_date: date) -> date:
    credit_key = _credit_style_key(row.get("account", ""))
    if credit_key:
        due_day = account_due_day_for_key(credit_key, CREDIT_CARD_DUE_DAY) if credit_key not in {"credit", PAYPAL_CREDIT_ACCOUNT_VALUE} else CREDIT_CARD_DUE_DAY
        return _credit_due_date_from_charge_date(scheduled_date, due_day=due_day)

    return scheduled_date


def _pending_account_for_rule(row: dict) -> str:
    credit_key = _credit_style_key(row.get("account", ""))
    if credit_key == PAYPAL_CREDIT_ACCOUNT_VALUE:
        return PAYPAL_CREDIT_ACCOUNT_VALUE
    if credit_key == "credit":
        return "credit"
    if credit_key:
        return account_label_for_key(credit_key)
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


def recurring_forecast_for_next_month(today: date | None = None) -> dict:
    today = today or date.today()

    if today.month == 12:
        year, month = today.year + 1, 1
    else:
        year, month = today.year, today.month + 1

    window_start = date(year, month, 1)
    window_end = date(year, month, calendar.monthrange(year, month)[1])
    return recurring_forecast_for_period(window_start, window_end, today=today)


def recurring_forecast_for_period(window_start: date, window_end: date, today: date | None = None) -> dict:
    """Preview recurring payments due in a period without writing pending rows."""
    today = today or date.today()
    pending_rows = load_pending()
    forecast_rows = []

    for row in load_recurring():
        for occurrence in _iter_scheduled_occurrences(row, stop_date=window_end, today=today):
            scheduled_date = occurrence["scheduled_date"]
            payment_due_date = _pending_due_date_for_rule(row, scheduled_date)

            if payment_due_date < window_start or payment_due_date > window_end:
                continue

            amount = normalize_amount(row.get("amount", 0))
            tx_type = str(row.get("type", "expense") or "expense").lower()
            account = _pending_account_for_rule(row)
            already_queued = _matching_pending_row_exists(
                pending_rows,
                row,
                scheduled_date=scheduled_date,
                pending_due_date=payment_due_date,
                account=account,
            )

            forecast_rows.append({
                "rule_id": row.get("id", ""),
                "name": row.get("name", ""),
                "type": tx_type,
                "category": row.get("category", ""),
                "account": account,
                "account_label": account_label_for_value(account),
                "is_auxiliary_account": is_auxiliary_account(account),
                "amount_value": amount,
                "amount_str": f"€ {amount:.2f}",
                "scheduled_date": scheduled_date.isoformat(),
                "payment_due_date": payment_due_date.isoformat(),
                "already_queued": already_queued,
                "status_label": "Already queued" if already_queued else "Forecast only",
                "impact_tone": "income" if tx_type == "income" else "expense",
            })

    forecast_rows = sorted(forecast_rows, key=lambda row: (row["payment_due_date"], row["name"]))

    expected_income = sum(row["amount_value"] for row in forecast_rows if row["type"] == "income")
    expected_outflow = sum(row["amount_value"] for row in forecast_rows if row["type"] != "income")
    expected_expenses = sum(row["amount_value"] for row in forecast_rows if row["type"] == "expense")
    expected_investments = sum(row["amount_value"] for row in forecast_rows if row["type"] == "investment")

    return {
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "window_label": window_start.strftime("%B %Y"),
        "items": forecast_rows,
        "count": len(forecast_rows),
        "expected_income": float(expected_income),
        "expected_outflow": float(expected_outflow),
        "expected_expenses": float(expected_expenses),
        "expected_investments": float(expected_investments),
        "net_impact": float(expected_outflow - expected_income),
    }


def _iter_due_dates_to_generate(row: dict, today: date):
    for occurrence in _iter_scheduled_occurrences(row, stop_date=today, today=today):
        scheduled_date = occurrence["scheduled_date"]
        last_generated = parse_date(row.get("last_generated"))
        if last_generated and scheduled_date <= last_generated:
            continue
        if scheduled_date <= today:
            yield scheduled_date


def _iter_scheduled_occurrences(row: dict, stop_date: date, today: date | None = None):
    today = today or date.today()
    frequency_months = parse_frequency_months(row.get("frequency"))
    max_occurrences = parse_max_occurrences(row.get("max_occurrences"))
    end_date = parse_date(row.get("end_date"))

    try:
        desired_day = int(row.get("day_of_month", 1))
    except (TypeError, ValueError):
        desired_day = 1

    scheduled_date = first_due_date(row, today)
    occurrence_index = 1

    for _ in range(2400):
        if scheduled_date > stop_date:
            break
        if end_date and scheduled_date > end_date:
            break
        if max_occurrences is not None and occurrence_index > max_occurrences:
            break

        yield {
            "scheduled_date": scheduled_date,
            "occurrence_index": occurrence_index,
        }

        scheduled_date = add_months(scheduled_date, frequency_months, desired_day)
        occurrence_index += 1


def _matching_pending_exists(row: dict, scheduled_date: date) -> bool:
    return _matching_pending_row_exists(
        load_pending(),
        row,
        scheduled_date=scheduled_date,
        pending_due_date=_pending_due_date_for_rule(row, scheduled_date),
        account=_pending_account_for_rule(row),
    )


def _matching_pending_row_exists(
    pending_rows: list[dict],
    row: dict,
    scheduled_date: date,
    pending_due_date: date,
    account: str,
) -> bool:
    due = pending_due_date.isoformat()
    rule_id = str(row.get("id", ""))
    name = str(row.get("name", ""))
    transaction_type = str(row.get("type", ""))
    category = str(row.get("category", ""))
    amount = normalize_amount(row.get("amount", 0))

    for tx in pending_rows:
        if tx.get("date_due") != due:
            continue

        same_source = tx.get("source") == "recurring" and str(tx.get("source_id", "")) == rule_id
        same_legacy_row = (
            tx.get("description") == name
            and tx.get("type") == transaction_type
            and tx.get("category") == category
            and str(tx.get("account", "auto")) == str(account)
            and abs(normalize_amount(tx.get("amount", 0)) - amount) < 0.01
        )

        if same_source or same_legacy_row:
            return True

    return False


def _nth_occurrence_date(row: dict, occurrence_number: int) -> date | None:
    if occurrence_number <= 0:
        return None

    frequency_months = parse_frequency_months(row.get("frequency"))
    try:
        desired_day = int(row.get("day_of_month", 1))
    except (TypeError, ValueError):
        desired_day = 1

    start = first_due_date(row, date.today())
    return add_months(start, frequency_months * (occurrence_number - 1), desired_day)


def _stop_rule_display(end_date: date | None, max_occurrences: int | None, last_occurrence: date | None) -> str:
    if max_occurrences is not None:
        if last_occurrence:
            return f"After {max_occurrences} occurrence{'s' if max_occurrences != 1 else ''} · last on {last_occurrence.isoformat()}"
        return f"After {max_occurrences} occurrence{'s' if max_occurrences != 1 else ''}"
    if end_date:
        return end_date.isoformat()
    return "Forever"


def _decorate_rule(row: dict) -> dict:
    decorated = dict(row)

    try:
        amount = float(decorated.get("amount", 0.0))
    except (TypeError, ValueError):
        amount = 0.0

    frequency = parse_frequency_months(decorated.get("frequency"))
    next_due = next_due_date_for_rule(decorated)
    last_generated = parse_date(decorated.get("last_generated"))
    generated_count = occurrence_count_until(decorated, last_generated)
    max_occurrences = parse_max_occurrences(decorated.get("max_occurrences"))
    end_date = parse_date(decorated.get("end_date"))
    stop_after_last_date = _nth_occurrence_date(decorated, max_occurrences) if max_occurrences else None
    finished = is_rule_finished(decorated)
    history = _recurring_history_summary(decorated)

    decorated["type"] = str(decorated.get("type", "expense") or "expense").lower()
    decorated["amount_value"] = amount
    decorated["amount_str"] = f"€ {amount:.2f}"
    decorated["frequency"] = frequency
    decorated["monthly_equivalent"] = amount / frequency if frequency else amount
    decorated["annual_equivalent"] = decorated["monthly_equivalent"] * 12
    decorated["frequency_label"] = "Monthly" if frequency == 1 else f"Every {frequency} months"
    decorated["next_payment"] = "—" if finished else next_due.isoformat()
    decorated["next_payment_sort"] = date.max if finished else next_due
    decorated["start_date"] = decorated.get("start_date", "") or "—"
    decorated["end_date"] = decorated.get("end_date", "") or ""
    decorated["end_date_display"] = decorated["end_date"] or "No end date"
    decorated["max_occurrences"] = decorated.get("max_occurrences", "") or ""
    decorated["max_occurrences_display"] = decorated["max_occurrences"] or "Forever"
    decorated["generated_count"] = generated_count
    decorated["max_occurrences_value"] = max_occurrences
    decorated["stop_after_last_date"] = stop_after_last_date.isoformat() if stop_after_last_date else ""
    decorated["stop_rule_display"] = _stop_rule_display(end_date, max_occurrences, stop_after_last_date)
    decorated["account_label"] = account_label_for_value(decorated.get("account", ""))
    decorated["is_auxiliary_account"] = is_auxiliary_account(decorated.get("account", ""))
    decorated["is_finished"] = finished
    decorated["finish_reason"] = _finish_reason(end_date, max_occurrences, generated_count, next_due)
    decorated["last_generated_sort"] = last_generated or date.min
    decorated.update(history)

    return decorated


def _finish_reason(end_date: date | None, max_occurrences: int | None, generated_count: int, next_due: date) -> str:
    if max_occurrences is not None and generated_count >= max_occurrences:
        return f"Stopped after {max_occurrences} occurrence{'s' if max_occurrences != 1 else ''}"
    if end_date and next_due > end_date:
        return f"Ended on {end_date.isoformat()}"
    return "Runs forever" if not end_date and max_occurrences is None else "Still active"


def _recurring_history_summary(row: dict) -> dict:
    history_rows = _history_rows_for_rule(row)
    executed = [tx for tx in history_rows if str(tx.get("status", "pending")).lower() != "pending"]
    pending = [tx for tx in history_rows if str(tx.get("status", "pending")).lower() == "pending"]

    generated_total = sum(normalize_amount(tx.get("amount", 0)) for tx in history_rows)
    executed_total = sum(normalize_amount(tx.get("amount", 0)) for tx in executed)
    pending_total = sum(normalize_amount(tx.get("amount", 0)) for tx in pending)

    tx_type = str(row.get("type", "expense") or "expense").lower()
    if tx_type == "income":
        total_label = "Total received"
    elif tx_type == "investment":
        total_label = "Total invested"
    else:
        total_label = "Total spent"

    return {
        "history_count": len(history_rows),
        "history_executed_count": len(executed),
        "history_pending_count": len(pending),
        "history_total": float(generated_total),
        "history_executed_total": float(executed_total),
        "history_pending_total": float(pending_total),
        "history_total_str": f"€ {generated_total:.2f}",
        "history_executed_total_str": f"€ {executed_total:.2f}",
        "history_pending_total_str": f"€ {pending_total:.2f}",
        "history_total_label": total_label,
    }


def _history_rows_for_rule(row: dict) -> list[dict]:
    rule_id = str(row.get("id", ""))
    name = str(row.get("name", ""))
    tx_type = str(row.get("type", ""))
    category = str(row.get("category", ""))
    seen_ids = set()
    rows = []

    for tx in load_pending():
        tx_id = str(tx.get("id", ""))
        same_source = tx.get("source") == "recurring" and str(tx.get("source_id", "")) == rule_id
        legacy_match = (
            not tx.get("source")
            and tx.get("description") == name
            and tx.get("type") == tx_type
            and tx.get("category") == category
        )

        if (same_source or legacy_match) and tx_id not in seen_ids:
            rows.append(tx)
            seen_ids.add(tx_id)

    return rows
