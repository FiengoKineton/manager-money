from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from money_manager.config import MAIN_ACCOUNT_KEY
from money_manager.repositories.account_events import append_event
from money_manager.repositories.pending import load_pending
from money_manager.repositories.recurring import load_recurring
from money_manager.services.account_config_service import (
    account_by_key,
    account_label_for_key,
    active_accounts,
    load_accounts_config,
    normalize_account_key,
    save_accounts_config,
)
from money_manager.services.account_ledger_service import account_balance_from_ledger, load_ledger
from money_manager.services.credit_settlement_service import (
    execute_credit_settlement,
    settlement_rows_for_account,
    sync_credit_settlements,
)
from money_manager.services.payment_method_service import load_payment_methods, save_payment_methods
from money_manager.services.profile_service import load_profile, save_profile

ACCOUNT_REFERENCE_FIELDS = [
    "linked_account_id",
    "funding_account_id",
    "settlement_account_id",
    "liability_account_id",
]


def account_closure_precheck(account_id: str) -> dict[str, Any]:
    key = normalize_account_key(account_id)
    account = account_by_key(key, include_archived=True)
    if not account:
        return {"ok": False, "error": "Account not found.", "blockers": ["Account not found."], "warnings": [], "account_id": key}

    legacy_balance = _legacy_account_balance(key)
    ledger_balance = account_balance_from_ledger(key)
    has_ledger = any(str(row.get("account_id") or "") == key for row in load_ledger(include_void=False))
    balance = ledger_balance if has_ledger else legacy_balance

    blockers: list[str] = []
    warnings: list[str] = []
    if key == MAIN_ACCOUNT_KEY:
        active_current = [row for row in active_accounts(include_main=True) if row.get("is_current_account") and row.get("key") != key]
        if not active_current:
            warnings.append("This is the last active current account. Select a replacement or confirm very carefully.")

    active_method_refs = _active_payment_method_refs(key)
    if active_method_refs:
        blockers.append(f"{len(active_method_refs)} active payment method reference(s) still point to this account.")

    dependent_accounts = [row for row in active_accounts(include_main=False) if str(row.get("parent_account_id") or row.get("parent_key") or "") == key]
    if dependent_accounts:
        blockers.append(f"{len(dependent_accounts)} active dependent account(s) still sit under this account.")

    sync_credit_settlements(sync_pending=True)
    open_settlements = [row for row in settlement_rows_for_account(key) if str(row.get("status") or "open") in {"open", "scheduled"}]
    if open_settlements:
        blockers.append(f"{len(open_settlements)} open credit settlement(s) use this account.")

    pending_rows = _pending_rows_for_account(key)
    if pending_rows:
        blockers.append(f"{len(pending_rows)} pending row(s) reference this account.")

    recurring_rows = _recurring_rows_for_account(key)
    if recurring_rows:
        blockers.append(f"{len(recurring_rows)} recurring rule(s) reference this account.")

    related = _other_dependency_counts(key)
    for name, count in related.items():
        if count:
            warnings.append(f"{count} {name} row(s) mention this account. Review before closing.")

    if abs(balance) >= 0.005:
        warnings.append(f"Current balance is € {balance:.2f}. Move or reconcile it before archive-only closure.")

    warnings.append("Future Bills/Mutui checks are not implemented yet; review those manually when that module exists.")

    available_replacements = [
        {"key": row.get("key"), "label": row.get("label") or row.get("name") or row.get("key")}
        for row in active_accounts(include_main=True)
        if row.get("key") != key and not row.get("is_container") and not row.get("is_closed")
    ]

    return {
        "ok": True,
        "account_id": key,
        "account": account,
        "balance": round(balance, 2),
        "legacy_balance": round(legacy_balance, 2),
        "ledger_balance": round(ledger_balance, 2),
        "balance_source": "ledger" if has_ledger else "legacy",
        "active_payment_methods": active_method_refs,
        "dependent_accounts": dependent_accounts,
        "open_settlements": open_settlements,
        "pending_rows": pending_rows,
        "recurring_rows": recurring_rows,
        "other_dependency_counts": related,
        "blockers": blockers,
        "warnings": warnings,
        "available_replacements": available_replacements,
        "can_archive_only": not blockers and abs(balance) < 0.005,
        "can_move_balance_then_archive": bool(available_replacements),
        "can_reassign_payment_methods": bool(active_method_refs and available_replacements),
        "can_settle_credit_now": bool(open_settlements),
        "can_move_future_settlements": bool(open_settlements and available_replacements),
    }


def close_account(account_id: str, options: Mapping[str, Any]) -> dict[str, Any]:
    key = normalize_account_key(account_id)
    replacement = normalize_account_key(options.get("replacement_account_id") or options.get("replacement_account") or "") if options.get("replacement_account_id") or options.get("replacement_account") else ""
    mode = str(options.get("closure_mode") or options.get("mode") or "archive_only")
    today = str(options.get("date") or date.today().isoformat())
    allow_nonzero = _truthy(options.get("confirm_nonzero_balance")) or _truthy(options.get("confirm_close_last_current"))

    precheck = account_closure_precheck(key)
    if not precheck.get("ok"):
        return precheck
    account = precheck["account"]
    warnings = list(precheck.get("warnings", []))
    actions: list[str] = []

    if replacement and replacement == key:
        return {"ok": False, "error": "Replacement account must be different.", "precheck": precheck}
    if replacement and not account_by_key(replacement, include_archived=False):
        return {"ok": False, "error": "Replacement account does not exist or is inactive.", "precheck": precheck}

    balance = float(precheck.get("balance") or 0.0)
    blockers = list(precheck.get("blockers", []))

    if mode in {"move_balance_then_archive", "close_with_replacement"}:
        if not replacement:
            return {"ok": False, "error": "Select a replacement account to move the balance.", "precheck": precheck}
        if abs(balance) >= 0.005:
            move_report = move_balance_to_replacement(key, replacement, today, balance=balance)
            actions.append("balance_moved" if move_report.get("ok") else "balance_move_failed")
            if not move_report.get("ok"):
                return {"ok": False, "error": move_report.get("error", "Could not move balance."), "precheck": precheck}
            balance = 0.0
        blockers = [b for b in blockers if "balance" not in b.lower()]

    if _truthy(options.get("reassign_payment_methods")) or mode in {"reassign_and_archive", "close_with_replacement"}:
        if not replacement:
            return {"ok": False, "error": "Select a replacement account to reassign payment methods.", "precheck": precheck}
        report = reassign_payment_methods(key, replacement)
        actions.append(f"payment_methods_reassigned:{report.get('changed_count', 0)}")
        blockers = [b for b in blockers if "payment method" not in b.lower()]

    if _truthy(options.get("settle_credit_now")) or mode == "settle_credit_now_then_close":
        report = settle_pending_credit_now(key)
        actions.append(f"credit_settled:{report.get('executed_count', 0)}")
        blockers = [b for b in blockers if "credit settlement" not in b.lower()]

    if _truthy(options.get("move_future_settlements")) or mode == "move_future_settlements_then_archive":
        if not replacement:
            return {"ok": False, "error": "Select a replacement account to move future settlements.", "precheck": precheck}
        report = move_future_credit_settlements(key, replacement)
        actions.append(f"future_settlements_moved:{report.get('changed_count', 0)}")
        blockers = [b for b in blockers if "credit settlement" not in b.lower()]

    # Re-run the safety check after optional repair actions.
    final_check = account_closure_precheck(key)
    hard_blockers = list(final_check.get("blockers", []))
    final_balance = float(final_check.get("balance") or 0.0)
    if abs(final_balance) >= 0.005 and mode == "archive_only" and not allow_nonzero:
        hard_blockers.append("Archive-only closure requires zero balance or explicit non-zero confirmation.")
    if hard_blockers and not _truthy(options.get("force_close")):
        return {"ok": False, "error": "Account cannot be closed safely yet.", "blockers": hard_blockers, "precheck": final_check}

    closed = _set_account_closed(key, replacement_account_id=replacement, closed_at=today)
    if not closed:
        return {"ok": False, "error": "Account could not be marked closed.", "precheck": final_check}
    actions.append("account_closed")
    profile_report = _update_profile_default_if_needed(key, replacement)
    if profile_report.get("changed"):
        actions.append("profile_default_updated")
    elif profile_report.get("warning"):
        warnings.append(profile_report["warning"])

    event = append_event({
        "event_type": "account_closure",
        "account_id": key,
        "replacement_account_id": replacement,
        "status": "completed",
        "details": {"mode": mode, "actions": actions, "final_balance": final_balance},
        "warnings": warnings,
    })
    return {"ok": True, "message": "Account closed safely.", "actions": actions, "event": event, "warnings": warnings}


def archive_account_only(account_id: str) -> dict[str, Any]:
    return close_account(account_id, {"mode": "archive_only"})


def move_balance_to_replacement(account_id: str, replacement_account_id: str, movement_date: str | None = None, *, balance: float | None = None) -> dict[str, Any]:
    key = normalize_account_key(account_id)
    replacement = normalize_account_key(replacement_account_id)
    if not replacement or key == replacement:
        return {"ok": False, "error": "Replacement account is invalid."}
    amount = abs(float(balance if balance is not None else account_closure_precheck(key).get("balance", 0.0)))
    if amount < 0.005:
        return {"ok": True, "moved": False, "amount": 0.0}
    from_key, to_key = (key, replacement) if (balance or 0) >= 0 else (replacement, key)
    from money_manager.services.internal_transfer_service import create_transfer

    result = create_transfer({
        "date": movement_date or date.today().isoformat(),
        "from_account": from_key,
        "to_account": to_key,
        "amount": f"{amount:.2f}",
        "transfer_kind": "account_closure_balance_move",
        "description": f"Account closure balance move: {account_label_for_key(key)} → {account_label_for_key(replacement)}",
    })
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error", "Transfer failed.")}
    return {"ok": True, "moved": True, "amount": amount, "transfer_id": result.get("transfer_id")}


def reassign_payment_methods(account_id: str, replacement_account_id: str) -> dict[str, Any]:
    key = normalize_account_key(account_id)
    replacement = normalize_account_key(replacement_account_id)
    payload = load_payment_methods()
    changed = 0
    for method in payload.get("payment_methods", []):
        if not method.get("is_active", True) or method.get("is_archived"):
            continue
        touched = False
        for field in ACCOUNT_REFERENCE_FIELDS:
            if str(method.get(field) or "") == key:
                method[field] = replacement
                touched = True
        if touched:
            method["updated_at"] = _now()
            changed += 1
    if changed:
        save_payment_methods(payload)
    return {"ok": True, "changed_count": changed}


def settle_pending_credit_now(account_id: str) -> dict[str, Any]:
    key = normalize_account_key(account_id)
    sync_credit_settlements(sync_pending=True)
    results = []
    for row in settlement_rows_for_account(key):
        if str(row.get("status") or "open") in {"open", "scheduled"}:
            results.append(execute_credit_settlement(row.get("id", ""), execution_date=date.today().isoformat()))
    return {"ok": True, "executed_count": len([item for item in results if item.get("ok")]), "results": results}


def move_future_credit_settlements(account_id: str, replacement_account_id: str) -> dict[str, Any]:
    from money_manager.repositories.credit_settlements import update_settlement

    key = normalize_account_key(account_id)
    replacement = normalize_account_key(replacement_account_id)
    changed = 0
    for row in settlement_rows_for_account(key):
        if str(row.get("status") or "open") not in {"open", "scheduled"}:
            continue
        if str(row.get("settlement_account_id") or "") != key:
            continue
        update_settlement(row.get("id", ""), {
            "settlement_account_id": replacement,
            "settlement_account_name_snapshot": account_label_for_key(replacement),
        })
        changed += 1
    return {"ok": True, "changed_count": changed}


def block_closure_if_unsafe(account_id: str) -> dict[str, Any]:
    report = account_closure_precheck(account_id)
    return {"ok": not report.get("blockers"), "blockers": report.get("blockers", []), "warnings": report.get("warnings", [])}


def _set_account_closed(account_id: str, *, replacement_account_id: str = "", closed_at: str | None = None) -> bool:
    key = normalize_account_key(account_id)
    config = load_accounts_config()
    changed = False
    for account in config.get("accounts", []):
        if account.get("key") != key:
            continue
        account["is_active"] = False
        account["is_closed"] = True
        account["closed_at"] = closed_at or date.today().isoformat()
        account["archived_at"] = account.get("archived_at") or account["closed_at"]
        account["replacement_account_id"] = replacement_account_id or account.get("replacement_account_id", "")
        account["updated_at"] = _now()
        changed = True
        break
    if changed:
        save_accounts_config(config)
    return changed


def _legacy_account_balance(account_id: str) -> float:
    try:
        from money_manager.services.account_service import account_balance_rows, main_account_transactions
        from money_manager.services.transaction_service import load_transactions

        df = load_transactions()
        if account_id == MAIN_ACCOUNT_KEY:
            main_rows = main_account_transactions(df)
            if not main_rows.empty and "signed_amount" in main_rows.columns:
                return float(main_rows["signed_amount"].sum())
            return 0.0
        rows = account_balance_rows(df)
        for row in rows:
            if row.get("key") == account_id:
                return float(row.get("balance", 0.0) or 0.0)
    except Exception:
        pass
    return 0.0


def _active_payment_method_refs(account_id: str) -> list[dict[str, Any]]:
    payload = load_payment_methods()
    refs: list[dict[str, Any]] = []
    for method in payload.get("payment_methods", []):
        if not method.get("is_active", True) or method.get("is_archived"):
            continue
        fields = [field for field in ACCOUNT_REFERENCE_FIELDS if str(method.get(field) or "") == account_id]
        if fields:
            refs.append({"id": method.get("id"), "name": method.get("name"), "fields": fields})
    return refs


def _pending_rows_for_account(account_id: str) -> list[dict[str, Any]]:
    rows = []
    for row in load_pending():
        if str(row.get("status") or "pending") != "pending":
            continue
        candidates = {str(row.get("account") or ""), str(row.get("account_key") or "")}
        normalized = {normalize_account_key(value) for value in candidates if value}
        if account_id in normalized:
            rows.append(row)
    return rows


def _recurring_rows_for_account(account_id: str) -> list[dict[str, Any]]:
    rows = []
    for row in load_recurring():
        if row.get("end_date"):
            continue
        account_value = str(row.get("account") or "")
        if account_value and normalize_account_key(account_value) == account_id:
            rows.append(row)
    return rows


def _other_dependency_counts(account_id: str) -> dict[str, int]:
    checks: dict[str, tuple[str, str]] = {
        "payable": ("money_manager.repositories.payables", "load_payables"),
        "debt": ("money_manager.repositories.debts", "load_debts"),
        "receivable": ("money_manager.repositories.receivables", "load_receivables"),
        "parent support": ("money_manager.repositories.parent_support", "load_parent_support_rows"),
        "expense project planned item": ("money_manager.repositories.expense_projects", "load_planned_items"),
    }
    result: dict[str, int] = {}
    for label, (module_name, func_name) in checks.items():
        try:
            module = __import__(module_name, fromlist=[func_name])
            loader = getattr(module, func_name)
            loaded = loader()
        except Exception:
            result[label] = 0
            continue
        count = 0
        for row in loaded if isinstance(loaded, list) else []:
            text_values = [str(row.get(field, "") or "") for field in ("account", "account_key", "payment_method", "description")]
            if any(normalize_account_key(value) == account_id for value in text_values if value):
                count += 1
        result[label] = count
    return result


def _update_profile_default_if_needed(account_id: str, replacement_account_id: str) -> dict[str, Any]:
    profile = load_profile()
    changed = False
    warning = ""
    replacement = replacement_account_id or ""
    if str(profile.get("default_current_account_id") or "") == account_id:
        profile["default_current_account_id"] = replacement
        changed = True
    if normalize_account_key(profile.get("default_main_account")) == account_id and str(profile.get("default_main_account") or ""):
        profile["default_main_account"] = replacement
        changed = True
    if changed:
        save_profile(profile)
    elif not replacement:
        warning = "Closed account had no replacement; default profile account was not changed."
    return {"changed": changed, "warning": warning}


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}
