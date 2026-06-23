#!/usr/bin/env python3
"""Lightweight regression check for the scoped account model."""

from __future__ import annotations

import contextlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _fmt(value) -> str:
    try:
        return f"€{float(value):.2f}"
    except Exception:
        return str(value)


def _default_user_id() -> str | None:
    try:
        from money_manager.config.user_paths import get_current_user_id

        current = get_current_user_id()
        if current:
            return current
        from money_manager.config.install_paths import USERS_DIR

        users = sorted([path.name for path in USERS_DIR.iterdir() if path.is_dir()])
        return users[0] if users else None
    except Exception:
        return None


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []
    user_id = _default_user_id()

    if user_id:
        from money_manager.config.user_paths import using_user

        user_ctx = using_user(user_id)
    else:
        user_ctx = contextlib.nullcontext()
        warnings.append("No existing user folder was found; checks will use safe defaults if possible.")

    if not user_id:
        print("Scoped account model check")
        print("User: <none>")
        print("No authenticated user or external user folder was found; validating built-in defaults only.")
        try:
            from money_manager.config.user_defaults import DEFAULT_ACCOUNTS, DEFAULT_PAYMENT_METHODS
            accounts = DEFAULT_ACCOUNTS.get("accounts", [])
            methods = DEFAULT_PAYMENT_METHODS.get("payment_methods", [])
            centers = [a for a in accounts if a.get("is_financial_center") or a.get("is_current_account") or a.get("account_kind") == "current_account"]
            print(f"Default accounts: {len(accounts)}")
            print(f"Default payment methods: {len(methods)}")
            print(f"Default financial centers: {len(centers)}")
            if not centers:
                print("ERROR: defaults define no financial center.")
                return 1
        except Exception as exc:
            print(f"ERROR: default model validation failed: {exc}")
            return 1
        print("\nOK: scoped account model default check completed.")
        return 0

    with user_ctx:
        try:
            from money_manager.services.schema_service import ensure_user_schema

            ensure_user_schema(user_id=user_id)
        except Exception as exc:
            warnings.append(f"Schema bootstrap skipped/failed: {exc}")

        try:
            from money_manager.services.account_config_service import all_accounts
            from money_manager.services.account_scope_service import financial_centers, resolve_account_scope, scope_balance_summary
            from money_manager.services.payment_method_service import all_payment_methods
        except Exception as exc:
            print(f"ERROR: scoped model imports failed: {exc}")
            return 2

        try:
            accounts = all_accounts(include_archived=True, include_main=True, user_id=user_id)
            methods = all_payment_methods(include_archived=True, user_id=user_id)
            print("Scoped account model check")
            if user_id:
                print(f"User: {user_id}")
            print(f"Accounts: {len(accounts)}")
            print(f"Payment methods: {len(methods)}")

            global_scope = resolve_account_scope("global", user_id=user_id)
            global_summary = scope_balance_summary(global_scope, user_id=user_id)
            print(f"Global: net={_fmt(global_summary.get('net_balance'))} projected={_fmt(global_summary.get('projected_net'))}")

            centers = financial_centers(user_id=user_id, include_archived=True)
            if not centers:
                errors.append("No financial centers were found.")

            for account in centers:
                account_id = str(account.get("id") or account.get("key") or "")
                if not account_id:
                    errors.append("A financial center is missing id/key.")
                    continue
                summary = scope_balance_summary(f"account:{account_id}", user_id=user_id)
                print(
                    f"- {summary.get('label') or account_id}: "
                    f"net={_fmt(summary.get('net_balance'))}, "
                    f"pending={_fmt(summary.get('pending_total'))}, "
                    f"recurring={_fmt(summary.get('recurring_monthly_total'))}, "
                    f"payables={_fmt(summary.get('payables_total'))}, "
                    f"projected={_fmt(summary.get('projected_net'))}"
                )

            for account in accounts:
                account_id = str(account.get("id") or account.get("key") or "")
                if not account_id:
                    continue
                if account.get("is_dependent_account") or account.get("parent_account_id") or account.get("parent_key"):
                    summary = scope_balance_summary(f"account:{account_id}", user_id=user_id)
                    print(f"  dependent {summary.get('label') or account_id}: net={_fmt(summary.get('net_balance'))}")
        except Exception as exc:
            message = str(exc)
            if "vault is locked" in message.casefold() or "No authenticated" in message:
                warnings.append(f"Scoped calculations skipped because user data is not currently readable: {exc}")
                try:
                    from money_manager.config.user_defaults import DEFAULT_ACCOUNTS, DEFAULT_PAYMENT_METHODS

                    accounts = DEFAULT_ACCOUNTS.get("accounts", [])
                    methods = DEFAULT_PAYMENT_METHODS.get("payment_methods", [])
                    centers = [a for a in accounts if a.get("is_financial_center") or a.get("is_current_account") or a.get("account_kind") == "current_account"]
                    print("Scoped account model default fallback")
                    print(f"Default accounts: {len(accounts)}")
                    print(f"Default payment methods: {len(methods)}")
                    print(f"Default financial centers: {len(centers)}")
                    if not centers:
                        errors.append("Defaults define no financial center.")
                except Exception as fallback_exc:
                    errors.append(f"Default fallback failed: {fallback_exc}")
            else:
                errors.append(f"Scoped calculations failed: {exc}")

    if warnings:
        print("\nWarnings")
        for warning in warnings:
            print(f"- {warning}")
    if errors:
        print("\nErrors")
        for error in errors:
            print(f"- {error}")
        return 1
    print("\nOK: scoped account model checks completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
