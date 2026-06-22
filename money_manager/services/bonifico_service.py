from __future__ import annotations

import re
from datetime import date
from typing import Any, Mapping

from money_manager.config import MAIN_NET_CREDIT_PENDING, account_options_for_forms, account_policy_for_key, normalize_account_key
from money_manager.config import DEBT_PAYMENT_CATEGORY
from money_manager.services.account_payment_policy_service import payment_selection_from_form
from money_manager.services.contact_service import add_contact, get_contact, list_contacts
from money_manager.services.debt_service import debt_by_id, register_debt_payment
from money_manager.repositories.debts import load_debts
from money_manager.repositories.payables import load_payables
from money_manager.services.payable_service import DEFAULT_PAYABLE_EXPENSE_CATEGORY, payable_by_id, register_payable_payment
from money_manager.services.transaction_service import account_balances_for_preview, save_transaction_payload

BONIFICO_PAYMENT_METHOD = "bonifico"
BONIFICO_TRANSFER_STATUS = "recorded"
TARGET_NORMAL_EXPENSE = "expense"
TARGET_DEBT = "debt"
TARGET_PAYABLE = "payable"
VALID_TARGET_TYPES = {TARGET_NORMAL_EXPENSE, TARGET_DEBT, TARGET_PAYABLE}


def record_bonifico(form: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    """Record a bank-transfer-style payment as a Money Manager expense.

    This service never executes a real transfer. It only writes a local expense
    transaction with stable snapshots of the recipient bank data available at
    recording time. When the transfer is linked to a debt or payable, the same
    transaction-router is used and the linked balance is reduced only after the
    transaction/pending row is successfully saved.
    """
    errors: list[str] = []

    target_type = _clean_text(form.get("bonifico_target_type") or form.get("target_type") or TARGET_NORMAL_EXPENSE).casefold()
    if target_type not in VALID_TARGET_TYPES:
        target_type = TARGET_NORMAL_EXPENSE

    amount = _parse_amount(form.get("amount"))
    if amount <= 0:
        errors.append("Amount must be greater than zero.")

    transfer_date = _clean_text(form.get("date")) or date.today().isoformat()
    try:
        date.fromisoformat(transfer_date)
    except ValueError:
        errors.append("Date is invalid.")

    source_account = _clean_text(form.get("account"))
    source_validation = _validate_source_account(source_account)
    if source_validation.get("error"):
        errors.append(str(source_validation["error"]))

    category = _clean_text(form.get("category")) or "Other"
    sub_category = _clean_text(form.get("sub_category"))
    description = _clean_multiline(form.get("description") or form.get("reason") or form.get("causale"))
    transfer_reference = _clean_text(form.get("transfer_reference"))

    linked_item: dict[str, Any] | None = None
    linked_item_id = ""
    recipient_fallback = ""

    if target_type == TARGET_DEBT:
        linked_item_id = _clean_text(form.get("debt_id") or form.get("target_id"))
        linked_item = debt_by_id(linked_item_id)
        if not linked_item or linked_item.get("status") != "active" or _parse_amount(linked_item.get("remaining_amount")) <= 0:
            errors.append("Select an active debt to pay with this bonifico.")
        else:
            remaining = _parse_amount(linked_item.get("remaining_amount"))
            if amount > remaining + 0.005:
                errors.append(f"Amount cannot exceed the selected debt remaining balance (€ {remaining:.2f}).")
            category = DEBT_PAYMENT_CATEGORY
            sub_category = _clean_text(linked_item.get("name"))
            recipient_fallback = _clean_text(linked_item.get("creditor"))
            if not description:
                description = f"Bonifico debt payment to {recipient_fallback}: {sub_category}".strip()
            if not transfer_reference:
                transfer_reference = f"Debt #{linked_item_id}"

    elif target_type == TARGET_PAYABLE:
        linked_item_id = _clean_text(form.get("payable_id") or form.get("target_id"))
        linked_item = payable_by_id(linked_item_id)
        if not linked_item or linked_item.get("status") != "active" or _parse_amount(linked_item.get("remaining_amount")) <= 0:
            errors.append("Select an active payable to pay with this bonifico.")
        else:
            remaining = _parse_amount(linked_item.get("remaining_amount"))
            if amount > remaining + 0.005:
                errors.append(f"Amount cannot exceed the selected payable remaining balance (€ {remaining:.2f}).")
            category = _clean_text(linked_item.get("category")) or DEFAULT_PAYABLE_EXPENSE_CATEGORY
            sub_category = _clean_text(linked_item.get("name"))
            recipient_fallback = _clean_text(linked_item.get("payee"))
            if not description:
                description = f"Bonifico payable payment to {recipient_fallback}: {sub_category}".strip()
            if not transfer_reference:
                transfer_reference = f"Payable #{linked_item_id}"

    contact_id = _clean_text(form.get("contact_id"))
    manual_name = _clean_text(form.get("manual_contact_name") or form.get("contact_name") or form.get("recipient_name"))
    save_contact = _as_bool(form.get("save_contact"))

    if not contact_id and recipient_fallback:
        matched_contact = _find_contact_by_name(recipient_fallback, user_id=user_id)
        if matched_contact:
            contact_id = _clean_text(matched_contact.get("id"))
        elif not manual_name:
            manual_name = recipient_fallback

    selected_contact: dict[str, Any] | None = None
    created_contact: dict[str, Any] | None = None

    if contact_id:
        selected_contact = get_contact(contact_id, user_id=user_id)
        if selected_contact is None or bool(selected_contact.get("is_archived")):
            errors.append("Selected contact was not found for this user.")
    elif not manual_name:
        errors.append("Select a contact or type a recipient name.")

    manual_bank = {
        "iban": _canonical_iban(form.get("iban")),
        "bic_swift": _clean_text(form.get("bic_swift") or form.get("bic") or form.get("swift")).upper(),
        "bank_name": _clean_text(form.get("bank_name")),
    }

    if errors:
        return {"ok": False, "errors": errors, "error": " ".join(errors), "target_type": target_type}

    if selected_contact is not None:
        contact_snapshot = _snapshot_from_contact(selected_contact)
    else:
        if save_contact:
            created_contact = add_contact(
                {
                    "type": "company",
                    "display_name": manual_name,
                    "company_name": manual_name,
                    "iban": manual_bank["iban"],
                    "bic_swift": manual_bank["bic_swift"],
                    "bank_name": manual_bank["bank_name"],
                },
                user_id=user_id,
            )
            contact_snapshot = _snapshot_from_contact(created_contact)
        else:
            contact_snapshot = {
                "contact_id": "",
                "contact_name": manual_name,
                "iban_snapshot": manual_bank["iban"],
                "bic_swift_snapshot": manual_bank["bic_swift"],
                "bank_name_snapshot": manual_bank["bank_name"],
            }

    payment_selection = payment_selection_from_form(form, source_validation["account_key"])
    bonifico_fields = {
        "payment_method": BONIFICO_PAYMENT_METHOD,
        "contact_id": contact_snapshot["contact_id"],
        "contact_name": contact_snapshot["contact_name"],
        "iban_snapshot": contact_snapshot["iban_snapshot"],
        "bic_swift_snapshot": contact_snapshot["bic_swift_snapshot"],
        "bank_name_snapshot": contact_snapshot["bank_name_snapshot"],
        "transfer_reference": transfer_reference,
        "transfer_status": BONIFICO_TRANSFER_STATUS,
    }

    if target_type == TARGET_DEBT:
        result = register_debt_payment(
            debt_id=linked_item_id,
            amount=amount,
            payment_date=transfer_date,
            account=source_validation["account_value"],
            description=description,
            payment_method=payment_selection["payment_method"],
            insufficient_action=payment_selection["insufficient_action"],
            extra_tx_fields=bonifico_fields,
        )
    elif target_type == TARGET_PAYABLE:
        result = register_payable_payment(
            payable_id=linked_item_id,
            amount=amount,
            payment_date=transfer_date,
            account=source_validation["account_value"],
            description=description,
            payment_method=payment_selection["payment_method"],
            insufficient_action=payment_selection["insufficient_action"],
            extra_tx_fields=bonifico_fields,
        )
    else:
        tx = {
            "type": "expense",
            "date": transfer_date,
            "category": category,
            "sub_category": sub_category,
            "amount": amount,
            "account": source_validation["account_value"],
            "description": description,
            **bonifico_fields,
        }
        result = save_transaction_payload(
            tx,
            payment_method=payment_selection["payment_method"],
            insufficient_action=payment_selection["insufficient_action"],
        )

    if not result.get("ok"):
        return {
            "ok": False,
            "errors": [result.get("error") or "Bonifico was not recorded."],
            "error": result.get("error") or "Bonifico was not recorded.",
            "created_contact": created_contact,
            "target_type": target_type,
        }

    return {
        "ok": True,
        "message": "Bonifico recorded in Money Manager only. No real bank transfer was executed.",
        "transaction_ids": result.get("transaction_ids", []),
        "pending_ids": result.get("pending_ids", []),
        "contact": selected_contact or created_contact,
        "created_contact": created_contact,
        "contact_snapshot": contact_snapshot,
        "target_type": target_type,
        "linked_item_id": linked_item_id,
    }


def bonifico_form_context() -> dict[str, Any]:
    """Return account options and linked-payment choices for the Bonifico form."""
    account_options: list[dict[str, Any]] = []
    for account in account_options_for_forms(include_credit=False):
        if account.get("kind") == "container" or bool(account.get("is_container")):
            continue
        account_options.append(account)

    contacts = list_contacts()
    return {
        "account_options": account_options,
        "account_balances": account_balances_for_preview(),
        "bonifico_targets": {
            "debts": _active_debt_options(contacts),
            "payables": _active_payable_options(contacts),
        },
    }


def _active_debt_options(contacts: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for debt in load_debts():
        remaining = _parse_amount(debt.get("remaining_amount"))
        if debt.get("status") != "active" or remaining <= 0:
            continue
        name = _clean_text(debt.get("name")) or f"Debt #{debt.get('id')}"
        creditor = _clean_text(debt.get("creditor"))
        rows.append(
            {
                "id": str(debt.get("id", "")),
                "name": name,
                "recipient_name": creditor,
                "remaining_amount": remaining,
                "remaining_amount_str": f"{remaining:.2f}",
                "category": DEBT_PAYMENT_CATEGORY,
                "sub_category": name,
                "contact_id": _match_contact_id(creditor, contacts),
                "description": f"Bonifico debt payment to {creditor}: {name}" if creditor else f"Bonifico debt payment: {name}",
                "reference": f"Debt #{debt.get('id', '')}",
                "label": f"{name} — {creditor} — € {remaining:.2f}" if creditor else f"{name} — € {remaining:.2f}",
            }
        )
    return rows


def _active_payable_options(contacts: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in load_payables():
        remaining = _parse_amount(item.get("remaining_amount"))
        if item.get("status") != "active" or remaining <= 0:
            continue
        name = _clean_text(item.get("name")) or f"Payable #{item.get('id')}"
        payee = _clean_text(item.get("payee"))
        category = _clean_text(item.get("category")) or DEFAULT_PAYABLE_EXPENSE_CATEGORY
        rows.append(
            {
                "id": str(item.get("id", "")),
                "name": name,
                "recipient_name": payee,
                "remaining_amount": remaining,
                "remaining_amount_str": f"{remaining:.2f}",
                "category": category,
                "sub_category": name,
                "contact_id": _match_contact_id(payee, contacts),
                "description": f"Bonifico payable payment to {payee}: {name}" if payee else f"Bonifico payable payment: {name}",
                "reference": f"Payable #{item.get('id', '')}",
                "label": f"{name} — {payee} — € {remaining:.2f}" if payee else f"{name} — € {remaining:.2f}",
            }
        )
    return rows


def _validate_source_account(value: str) -> dict[str, Any]:
    options = bonifico_form_context()["account_options"]
    raw = _clean_text(value)

    for option in options:
        option_value = str(option.get("value") or "")
        option_key = str(option.get("key") or "")
        option_label = str(option.get("display_label") or option.get("label") or "")
        candidates = {option_value, option_key, option_label, str(option.get("label") or "")}
        if raw in candidates:
            key = normalize_account_key(option_value or option_key or raw)
            if account_policy_for_key(key) == MAIN_NET_CREDIT_PENDING:
                return {"error": "Credit-card routes are not valid source accounts for Bonifico."}
            return {"account_value": option_value, "account_key": key, "account": option}

    key = normalize_account_key(raw)
    if raw == "" and key:
        return {"account_value": "", "account_key": key, "account": options[0] if options else {}}

    return {"error": "Selected source account is not valid or is archived."}


def _snapshot_from_contact(contact: Mapping[str, Any]) -> dict[str, str]:
    return {
        "contact_id": _clean_text(contact.get("id")),
        "contact_name": _clean_text(contact.get("display_name") or contact.get("company_name") or " ".join(part for part in [contact.get("first_name"), contact.get("last_name")] if part)),
        "iban_snapshot": _canonical_iban(contact.get("iban")),
        "bic_swift_snapshot": _clean_text(contact.get("bic_swift")).upper(),
        "bank_name_snapshot": _clean_text(contact.get("bank_name")),
    }


def _find_contact_by_name(name: str, user_id: str | None = None) -> dict[str, Any] | None:
    wanted = _name_key(name)
    if not wanted:
        return None
    for contact in list_contacts(user_id=user_id):
        if _contact_name_matches(contact, wanted):
            return contact
    return None


def _match_contact_id(name: str, contacts: list[Mapping[str, Any]]) -> str:
    wanted = _name_key(name)
    if not wanted:
        return ""
    for contact in contacts:
        if _contact_name_matches(contact, wanted):
            return _clean_text(contact.get("id"))
    return ""


def _contact_name_matches(contact: Mapping[str, Any], wanted: str) -> bool:
    names = [
        contact.get("display_name"),
        contact.get("company_name"),
        " ".join(part for part in [contact.get("first_name"), contact.get("last_name")] if part),
    ]
    return any(_name_key(name) == wanted for name in names if name)


def _name_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", _clean_text(value).casefold())


def _parse_amount(value: Any) -> float:
    try:
        return round(float(str(value or "0").replace(",", ".")), 2)
    except (TypeError, ValueError):
        return 0.0


def _clean_text(value: Any) -> str:
    text = str(value or "").strip()
    if text.casefold() in {"nan", "none", "null"}:
        return ""
    return " ".join(text.split())


def _clean_multiline(value: Any) -> str:
    text = str(value or "").strip()
    if text.casefold() in {"nan", "none", "null"}:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [" ".join(line.split()) for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


def _canonical_iban(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).upper()


def _as_bool(value: Any) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "on"}
