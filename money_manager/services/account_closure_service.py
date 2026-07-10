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
    configured_account_key,
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
    "parent_account_id",
]


def account_closure_precheck(account_id: str) -> dict[str, Any]:
    key = configured_account_key(account_id)
    if not key:
        return {"ok": False, "error": "Account not found.", "blockers": ["Account not found."], "warnings": [], "account_id": str(account_id or "")}
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
        blockers.append("The built-in Main account cannot be closed. Rename it or move activity to another current account instead.")

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

    related_rows = _other_dependencies(key)
    related = {name: len(rows) for name, rows in related_rows.items()}
    for name, count in related.items():
        if count:
            blockers.append(f"{count} active {name} row(s) reference this account. Reassign or finish them before closing.")

    if abs(balance) >= 0.005:
        warnings.append(f"Current balance is € {balance:.2f}. Move or reconcile it before archive-only closure.")

    warnings.append("Future-bill dependencies are not available in this repository, so review those manually if you use an external bills module.")

    available_replacements = [
        {"key": row.get("key"), "label": row.get("label") or row.get("name") or row.get("key")}
        for row in active_accounts(include_main=True)
        if row.get("key") != key
        and not row.get("is_container")
        and not row.get("is_closed")
        and not row.get("is_liability")
        and str(row.get("account_kind") or row.get("type") or "") != "credit_card_liability"
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
        "other_dependencies": related_rows,
        "blockers": blockers,
        "warnings": warnings,
        "available_replacements": available_replacements,
        "can_archive_only": not blockers and abs(balance) < 0.005,
        "can_move_balance_then_archive": bool(available_replacements),
        "can_reassign_payment_methods": bool(active_method_refs and available_replacements),
        "can_settle_credit_now": bool(open_settlements),
        "can_move_future_settlements": bool(open_settlements and available_replacements),
        "cashflow_account": _cashflow_account(exclude_key=key),
    }


def close_account(account_id: str, options: Mapping[str, Any]) -> dict[str, Any]:
    key = configured_account_key(account_id)
    if not key:
        return {"ok": False, "error": "Account not found."}
    replacement_raw = options.get("replacement_account_id") or options.get("replacement_account") or ""
    replacement = configured_account_key(replacement_raw) if replacement_raw else ""
    if replacement_raw and not replacement:
        return {"ok": False, "error": "Replacement account does not exist or is inactive."}
    mode = str(options.get("closure_mode") or options.get("mode") or "archive_only")
    balance_action = str(options.get("balance_action") or "").strip().casefold()
    today = str(options.get("date") or date.today().isoformat())

    if not _truthy(options.get("confirm_close")):
        return {"ok": False, "error": "Confirm that you understand the account will be closed before continuing."}

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

    balance_destination = ""
    if balance_action in {"transfer", "move_to_replacement"} or mode in {"move_balance_then_archive", "close_with_replacement"}:
        if not replacement:
            return {"ok": False, "error": "Select a replacement account for the remaining balance.", "precheck": precheck}
        balance_destination = replacement
    elif balance_action in {"cash", "liquidate_to_cash", "liquidate"}:
        cashflow = _cashflow_account(exclude_key=key)
        balance_destination = str(cashflow.get("key") or "") if cashflow else ""
        if not balance_destination:
            return {"ok": False, "error": "No open CashFlow/cash account is available for liquidation.", "precheck": precheck}

    if balance_destination:
        if balance_destination == key:
            return {"ok": False, "error": "Balance destination must be different from the account being closed.", "precheck": precheck}
        if abs(balance) >= 0.005:
            move_report = move_balance_to_replacement(key, balance_destination, today, balance=balance)
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

    if _truthy(options.get("reassign_dependent_accounts")):
        if not replacement:
            return {"ok": False, "error": "Select a replacement account to reassign dependent accounts.", "precheck": precheck}
        report = reassign_dependent_accounts(key, replacement)
        actions.append(f"dependent_accounts_reassigned:{report.get('changed_count', 0)}")
        blockers = [b for b in blockers if "dependent account" not in b.lower()]

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
    if abs(final_balance) >= 0.005:
        hard_blockers.append("The account still has a non-zero balance. Transfer it or liquidate it to CashFlow first.")
    if hard_blockers:
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
        "details": {
            "mode": mode,
            "balance_action": balance_action,
            "balance_destination_account_id": balance_destination,
            "actions": actions,
            "final_balance": final_balance,
        },
        "warnings": warnings,
    })
    return {"ok": True, "message": "Account closed safely.", "actions": actions, "event": event, "warnings": warnings}


def archive_account_only(account_id: str) -> dict[str, Any]:
    return close_account(account_id, {"mode": "archive_only", "confirm_close": "1"})


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


def reassign_dependent_accounts(account_id: str, replacement_account_id: str) -> dict[str, Any]:
    key = normalize_account_key(account_id)
    replacement = normalize_account_key(replacement_account_id)
    config = load_accounts_config()
    changed = 0
    for account in config.get("accounts", []):
        parent = str(account.get("parent_account_id") or account.get("parent_key") or "")
        if parent != key or not account.get("is_active", True) or account.get("is_closed"):
            continue
        account["parent_account_id"] = replacement
        account["parent_key"] = replacement
        account["updated_at"] = _now()
        changed += 1
    if changed:
        save_accounts_config(config)
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
        candidates = {
            str(row.get(field) or "")
            for field in ("account", "account_id", "account_key", "account_key_snapshot", "funding_account_id", "settlement_account_id")
        }
        normalized = {resolved for value in candidates if value for resolved in [configured_account_key(value)] if resolved}
        if account_id in normalized:
            rows.append(row)
    return rows


def _recurring_rows_for_account(account_id: str) -> list[dict[str, Any]]:
    rows = []
    try:
        from money_manager.services.recurring_service import is_rule_finished
    except Exception:
        is_rule_finished = None
    for row in load_recurring():
        if is_rule_finished and is_rule_finished(row):
            continue
        candidates = [str(row.get(field) or "") for field in ("account", "account_id", "account_key", "preferred_account_id", "funding_account_id")]
        if any(configured_account_key(value) == account_id for value in candidates if value):
            rows.append(row)
    return rows


def _other_dependencies(account_id: str) -> dict[str, list[dict[str, Any]]]:
    checks: dict[str, tuple[str, str, str | None]] = {
        "payable": ("money_manager.repositories.payables", "load_payables", None),
        "debt": ("money_manager.repositories.debts", "load_debts", None),
        "receivable": ("money_manager.repositories.receivables", "load_receivables", None),
        "parent support rule": ("money_manager.repositories.parent_support", "load_rules", None),
        "expense project planned item": ("money_manager.repositories.expense_projects", "load_planned_items", None),
        "investment asset": ("money_manager.repositories.investments", "load_investment_assets", None),
        "mortgage": ("money_manager.services.mortgage_service", "load_mortgages", "mortgages"),
        "savings goal": ("money_manager.services.savings_goal_service", "load_savings_goals", "goals"),
    }
    result: dict[str, list[dict[str, Any]]] = {}
    for label, (module_name, func_name, collection_key) in checks.items():
        try:
            module = __import__(module_name, fromlist=[func_name])
            loader = getattr(module, func_name)
            loaded = loader()
        except Exception:
            result[label] = []
            continue
        if collection_key and isinstance(loaded, Mapping):
            loaded = loaded.get(collection_key, [])
        matches: list[dict[str, Any]] = []
        for row in loaded if isinstance(loaded, list) else []:
            if not isinstance(row, Mapping) or not _dependency_is_active(label, row):
                continue
            text_values = [
                str(row.get(field, "") or "")
                for field in (
                    "account",
                    "account_id",
                    "account_key",
                    "preferred_account_id",
                    "funding_account_id",
                    "settlement_account_id",
                )
            ]
            if any(configured_account_key(value) == account_id for value in text_values if value):
                matches.append(dict(row))
        result[label] = matches
    return result


def _dependency_is_active(label: str, row: Mapping[str, Any]) -> bool:
    if label == "investment asset":
        return _truthy(row.get("active"))
    if label == "mortgage":
        return bool(row.get("is_active", True))
    if label == "savings goal":
        return str(row.get("status") or "active").casefold() in {"active", "paused"}
    if label == "parent support rule":
        if not _truthy(row.get("active")):
            return False
        raw_end = str(row.get("end_date") or "").strip()
        if not raw_end:
            return True
        try:
            return date.fromisoformat(raw_end) >= date.today()
        except ValueError:
            return True
    return str(row.get("status") or "active").casefold() in {"active", "pending", "pocket"}


def _cashflow_account(exclude_key: str = "") -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for account in active_accounts(include_main=True):
        key = str(account.get("key") or account.get("id") or "")
        kind = str(account.get("account_kind") or account.get("type") or "")
        if not key or key == exclude_key or account.get("is_container") or account.get("is_liability"):
            continue
        if key in {"cash_flow", "cashflow", "cash"} or kind == "cash":
            candidates.append(dict(account))
    if not candidates:
        return None
    def _sort_order(row: Mapping[str, Any]) -> tuple[int, int]:
        try:
            display_order = int(float(row.get("display_order") or 1000))
        except (TypeError, ValueError):
            display_order = 1000
        return (0 if str(row.get("key") or "") == "cash_flow" else 1, display_order)

    candidates.sort(key=_sort_order)
    account = candidates[0]
    return {"key": str(account.get("key") or account.get("id") or ""), "label": str(account.get("label") or account.get("name") or "CashFlow")}


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
