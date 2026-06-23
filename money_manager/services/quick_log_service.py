from __future__ import annotations

from datetime import date

from money_manager.config import categories_for
from money_manager.config.categories import PARENT_SUPPORT_CATEGORIES, PARENT_SUPPORT_KINDS, DEFAULT_PARENT_SUPPORT_CATEGORY
from money_manager.repositories.debts import load_debts
from money_manager.repositories.expense_projects import load_planned_items, load_projects
from money_manager.repositories.payables import load_payables
from money_manager.repositories.receivables import load_receivables
from money_manager.services.debt_service import add_debt_from_form, pay_debt_from_form
from money_manager.services.internal_transfer_service import create_transfer
from money_manager.services.payment_form_service import account_options_for_payment_forms, payment_method_options_for_forms
from money_manager.services.expense_project_service import add_planned_item_from_form, pay_planned_item_from_form
from money_manager.services.parent_support_service import add_entry_from_form as add_parent_support_entry
from money_manager.services.payable_service import add_payable_from_form, pay_payable_from_form
from money_manager.services.receivable_service import add_receivable_from_form, collect_receivable_from_form
from money_manager.services.sparagnat_service import add_entry_from_form as add_sparagnat_entry, KIND_LABELS as SPARAGNAT_KIND_LABELS


QUICK_LOG_MODES = [
    {
        "key": "internal_transfer",
        "label": "Internal transfer",
        "description": "Moves money between Main Bank and any configured account.",
        "target": "Internal Transfers + account balances",
        "affects_net": "No income/expense; Main → Pre-paid adds €1 fee",
    },
    {
        "key": "parent_support",
        "label": "Parent support",
        "description": "Money given to you or expenses covered by your parents. Stored in Parent Support, not in the main net.",
        "target": "Parent Support",
        "affects_net": "No",
    },
    {
        "key": "sparagnat",
        "label": "Sparagnat e Fottut",
        "description": "Saved expense or cash collected. Stored in the separate tracker.",
        "target": "Sparagnat e Fottut",
        "affects_net": "No",
    },
    {
        "key": "debt_create",
        "label": "Add debt I owe",
        "description": "Creates a tracked debt without creating a bank transaction.",
        "target": "Debts I Owe",
        "affects_net": "No",
    },
    {
        "key": "debt_pay",
        "label": "Pay debt I owe",
        "description": "Registers a debt payment and decreases the remaining debt.",
        "target": "Debts I Owe + Transactions",
        "affects_net": "Yes, if paid from main/credit account",
    },
    {
        "key": "receivable_create",
        "label": "Money owed to me",
        "description": "Tracks money someone owes you and records the original money leaving your selected account.",
        "target": "Money Owed to Me + Transactions",
        "affects_net": "Yes, when money leaves the account",
    },
    {
        "key": "receivable_collect",
        "label": "Collect money owed to me",
        "description": "Registers a repayment and decreases the remaining receivable.",
        "target": "Money Owed to Me + Transactions",
        "affects_net": "Yes, if collected into main account",
    },
    {
        "key": "payable_create",
        "label": "Add payable",
        "description": "Creates a thing you still need to pay, without recording the payment yet.",
        "target": "Payables",
        "affects_net": "No",
    },
    {
        "key": "payable_pay",
        "label": "Pay payable",
        "description": "Records a full/partial payment and updates the payable. Linked projects are updated by link only.",
        "target": "Payables + Transactions",
        "affects_net": "Yes, if paid from main/credit account",
    },
    {
        "key": "project_plan",
        "label": "Add project expected cost",
        "description": "Adds a forecast/planned item to an existing project. No payment is created.",
        "target": "Expense Projects",
        "affects_net": "No",
    },
    {
        "key": "project_pay",
        "label": "Pay project item",
        "description": "Pays a planned project item and attaches the generated transaction to that project.",
        "target": "Expense Projects + Transactions",
        "affects_net": "Yes, if paid from main/credit account",
    },
]


def quick_log_context() -> dict:
    from money_manager.services.cache_service import cached_calculation

    return cached_calculation("quick_log.context", _quick_log_context_uncached)


def _quick_log_context_uncached() -> dict:
    debts = [_prepare_amount_row(row) for row in load_debts() if _is_active(row) and _amount(row.get("remaining_amount")) > 0]
    payables = [_prepare_amount_row(row) for row in load_payables() if _is_active(row) and _amount(row.get("remaining_amount")) > 0]
    receivables = [_prepare_amount_row(row) for row in load_receivables() if _is_active(row) and _amount(row.get("remaining_amount")) > 0]
    projects = [row for row in load_projects() if str(row.get("status", "active") or "active").casefold() == "active"]
    project_names = {str(row.get("id")): row.get("name", f"Project {row.get('id')}") for row in projects}

    planned_items = []
    for item in load_planned_items():
        if not _is_active(item) or _amount(item.get("remaining_amount")) <= 0:
            continue
        if not project_names.get(str(item.get("project_id"))):
            continue
        if str(item.get("payable_id", "")).strip():
            # Pay linked payables from Payables; project only mirrors them.
            continue
        item = _prepare_amount_row(item)
        item["project_name"] = project_names.get(str(item.get("project_id")), "Project")
        item["combined_id"] = f"{item.get('project_id')}:{item.get('id')}"
        planned_items.append(item)

    return {
        "quick_log_modes": QUICK_LOG_MODES,
        "quick_log_context": {
            "debts": debts,
            "payables": payables,
            "receivables": receivables,
            "projects": projects,
            "planned_items": planned_items,
            "parent_support_kinds": PARENT_SUPPORT_KINDS,
            "parent_support_categories": PARENT_SUPPORT_CATEGORIES,
            "parent_support_default_category": DEFAULT_PARENT_SUPPORT_CATEGORY,
            "sparagnat_kinds": SPARAGNAT_KIND_LABELS,
            "expense_categories": categories_for("expense"),
            "account_options": account_options_for_payment_forms(include_credit=True),
            "payment_method_options": payment_method_options_for_forms(),
            "transfer_account_options": account_options_for_payment_forms(include_credit=False),
        },
    }


def handle_quick_log(form) -> dict:
    mode = str(form.get("quick_mode", "")).strip()
    if mode not in {item["key"] for item in QUICK_LOG_MODES}:
        return {"ok": False, "error": "Choose what kind of special log you want to create."}

    payload = _base_payload(form)

    if mode == "internal_transfer":
        result = create_transfer({
            "date": form.get("date") or date.today().isoformat(),
            "from_account_id": form.get("from_account_id") or form.get("from_account", ""),
            "to_account_id": form.get("to_account_id") or form.get("to_account", ""),
            "from_account": form.get("from_account", ""),
            "to_account": form.get("to_account", ""),
            "amount": form.get("amount", "0"),
            "description": form.get("description", ""),
            "move_all": form.get("move_all", ""),
        })
        if not result.get("ok"):
            return result
        return _ok(result.get("message", "Internal transfer saved."))

    if mode == "parent_support":
        payload.update({
            "kind": form.get("support_kind") or "covered_expense",
            "parent": form.get("person", ""),
            "category": form.get("support_category") or DEFAULT_PARENT_SUPPORT_CATEGORY,
            "payment_method": form.get("payment_method", ""),
        })
        add_parent_support_entry(payload)
        return _ok("Parent Support entry saved. It does not affect the main net.")

    if mode == "sparagnat":
        payload.update({
            "kind": form.get("sparagnat_kind") or "saved_expense",
            "person": form.get("person", ""),
            "category": form.get("category", ""),
        })
        add_sparagnat_entry(payload)
        return _ok("Sparagnat entry saved in its own tracker.")

    if mode == "debt_create":
        name = _first(form.get("name"), form.get("description"), "Debt")
        amount = _amount(form.get("amount"))
        if amount <= 0:
            return {"ok": False, "error": "Debt amount must be greater than zero."}
        add_debt_from_form({
            "name": name,
            "creditor": form.get("person", ""),
            "original_amount": amount,
            "remaining_amount": form.get("remaining_amount") or amount,
            "account": form.get("account", ""),
            "account_id": form.get("account_id") or form.get("account", ""),
            "payment_method_id": form.get("payment_method_id", ""),
            "start_date": form.get("date") or date.today().isoformat(),
            "due_date": form.get("due_date", ""),
            "description": form.get("description", ""),
        })
        return _ok("Debt created. No payment was recorded yet, so the net is unchanged.")

    if mode == "debt_pay":
        debt_id = form.get("debt_id", "")
        if not debt_id:
            return {"ok": False, "error": "Select the debt you are paying."}
        pay_debt_from_form({**payload, "id": debt_id})
        return _ok("Debt payment saved and the debt remaining amount was updated.")

    if mode == "receivable_create":
        amount = _amount(form.get("amount"))
        if amount <= 0:
            return {"ok": False, "error": "Receivable amount must be greater than zero."}
        add_receivable_from_form({
            "name": _first(form.get("name"), form.get("description"), "Money owed to me"),
            "debtor": form.get("person", ""),
            "original_amount": amount,
            "remaining_amount": form.get("remaining_amount") or amount,
            "account": form.get("account", ""),
            "account_id": form.get("account_id") or form.get("account", ""),
            "payment_method_id": form.get("payment_method_id", ""),
            "start_date": form.get("date") or date.today().isoformat(),
            "due_date": form.get("due_date", ""),
            "description": form.get("description", ""),
        })
        return _ok("Receivable created. The original money movement was recorded as an expense.")

    if mode == "receivable_collect":
        receivable_id = form.get("receivable_id", "")
        if not receivable_id:
            return {"ok": False, "error": "Select the receivable you are collecting."}
        collect_receivable_from_form({**payload, "id": receivable_id})
        return _ok("Receivable collection saved and the remaining amount was updated.")

    if mode == "payable_create":
        amount = _amount(form.get("amount"))
        if amount <= 0:
            return {"ok": False, "error": "Payable amount must be greater than zero."}
        add_payable_from_form({
            "name": _first(form.get("name"), form.get("description"), "Payable"),
            "payee": form.get("person", ""),
            "original_amount": amount,
            "remaining_amount": form.get("remaining_amount") or amount,
            "category": form.get("category") or "Payable",
            "account": form.get("account", ""),
            "account_id": form.get("account_id") or form.get("account", ""),
            "payment_method_id": form.get("payment_method_id", ""),
            "start_date": form.get("date") or date.today().isoformat(),
            "due_date": form.get("due_date", ""),
            "description": form.get("description", ""),
        })
        return _ok("Payable created. No payment was recorded yet, so the net is unchanged.")

    if mode == "payable_pay":
        payable_id = form.get("payable_id", "")
        if not payable_id:
            return {"ok": False, "error": "Select the payable you are paying."}
        pay_payable_from_form({**payload, "id": payable_id})
        return _ok("Payable payment saved and linked project mirrors were updated if needed.")

    if mode == "project_plan":
        project_id = _safe_int(form.get("project_id"))
        amount = _amount(form.get("amount"))
        if project_id is None:
            return {"ok": False, "error": "Select the project."}
        if amount <= 0:
            return {"ok": False, "error": "Expected project cost must be greater than zero."}
        add_planned_item_from_form(project_id, {
            "name": _first(form.get("name"), form.get("description"), "Expected cost"),
            "vendor": form.get("person", ""),
            "original_amount": amount,
            "remaining_amount": form.get("remaining_amount") or amount,
            "category": form.get("category") or "Construction",
            "sub_category": form.get("sub_category", ""),
            "account": form.get("account", ""),
            "account_id": form.get("account_id") or form.get("account", ""),
            "payment_method_id": form.get("payment_method_id", ""),
            "start_date": form.get("date") or date.today().isoformat(),
            "due_date": form.get("due_date", ""),
            "description": form.get("description", ""),
        })
        return _ok("Expected project cost added. No payment was recorded yet.")

    if mode == "project_pay":
        project_id, item_id = _project_item_ids(form.get("project_item_id", ""))
        if project_id is None or item_id is None:
            return {"ok": False, "error": "Select the project item you are paying."}
        pay_planned_item_from_form(project_id, {**payload, "item_id": item_id})
        return _ok("Project payment saved and attached to the project actuals.")

    return {"ok": False, "error": "This quick log mode is not supported yet."}


def _base_payload(form) -> dict:
    return {
        "date": form.get("date") or date.today().isoformat(),
        "amount": form.get("amount", "0"),
        "account": form.get("account", ""),
        "account_id": form.get("account_id") or form.get("account", ""),
        "payment_method_id": form.get("payment_method_id", ""),
        "description": form.get("description", ""),
        "account_payment_method": form.get("account_payment_method", ""),
        "account_insufficient_action": form.get("account_insufficient_action", ""),
    }


def _ok(message: str) -> dict:
    return {"ok": True, "message": message}


def _is_active(row: dict) -> bool:
    return str(row.get("status", "active") or "active").casefold() == "active"


def _prepare_amount_row(row: dict) -> dict:
    row = dict(row)
    row["original_amount"] = _amount(row.get("original_amount"))
    row["remaining_amount"] = _amount(row.get("remaining_amount"))
    row["remaining_amount_str"] = f"{row['remaining_amount']:.2f}"
    row["original_amount_str"] = f"{row['original_amount']:.2f}"
    return row


def _amount(value) -> float:
    try:
        return max(0.0, float(str(value or "0").replace(",", ".")))
    except (TypeError, ValueError):
        return 0.0


def _safe_int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _first(*values) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _project_item_ids(value: str):
    text = str(value or "")
    if ":" not in text:
        return None, None
    project_raw, item_raw = text.split(":", 1)
    return _safe_int(project_raw), _safe_int(item_raw)
