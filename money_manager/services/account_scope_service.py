from __future__ import annotations

from datetime import date
from typing import Any, Mapping

import pandas as pd

from money_manager.config import MAIN_ACCOUNT_KEY
from money_manager.services.account_config_service import (
    account_by_key,
    account_label_for_key,
    all_accounts,
    normalize_account_key,
)

SCOPE_GLOBAL = "global"
SCOPE_ACCOUNT_PREFIX = "account:"
ROLLUP_TO_PARENT = "roll_up_to_parent"
STANDALONE = "standalone"
OWN_ONLY = "own_only"


def _clean_text(value: Any) -> str:
    text = str(value or "").strip().casefold()
    if text in {"nan", "none", "null"}:
        return ""
    return " ".join(text.split())


def _account_id(account: Mapping[str, Any] | None) -> str:
    if not account:
        return ""
    return str(account.get("key") or account.get("id") or "").strip()


def _is_active(account: Mapping[str, Any], include_archived: bool = False) -> bool:
    if include_archived:
        return True
    return bool(account.get("is_active", True)) and not bool(account.get("is_closed")) and not bool(account.get("is_archived"))


def _is_liquid_account(account: Mapping[str, Any]) -> bool:
    kind = str(account.get("account_kind") or account.get("type") or "")
    return kind not in {"container", "credit_card_liability"} and not bool(account.get("is_container")) and not bool(account.get("is_liability"))


def _is_financial_center(account: Mapping[str, Any]) -> bool:
    kind = str(account.get("account_kind") or account.get("type") or "")
    if kind == "current_account" or bool(account.get("is_current_account")):
        return True
    if bool(account.get("is_container")) or bool(account.get("is_liability")) or kind == "credit_card_liability":
        return False
    if bool(account.get("is_dependent_account")) and str(account.get("liquidity_rollup_policy") or "") != STANDALONE:
        return False
    return bool(account.get("is_financial_center")) or str(account.get("liquidity_rollup_policy") or "") == STANDALONE




def _is_technical_account(account: Mapping[str, Any]) -> bool:
    kind = str(account.get("account_kind") or account.get("type") or "")
    return bool(account.get("is_container")) or bool(account.get("is_liability")) or kind in {"container", "credit_card_liability", "external_account"}


def _is_current_center(account: Mapping[str, Any]) -> bool:
    kind = str(account.get("account_kind") or account.get("type") or "")
    return kind == "current_account" or bool(account.get("is_current_account"))


def _is_cashflow_center(account: Mapping[str, Any]) -> bool:
    key = _account_id(account)
    kind = str(account.get("account_kind") or account.get("type") or "")
    if bool(account.get("is_dependent_account")) or str(account.get("parent_account_id") or account.get("parent_key") or ""):
        return False
    if key in {"cash_flow", "cashflow", "cash"}:
        return True
    if kind in {"cash", "investment_cash"} and (bool(account.get("is_financial_center")) or str(account.get("liquidity_rollup_policy") or "") == STANDALONE):
        return True
    return False


def account_level(account: Mapping[str, Any]) -> int:
    if _is_current_center(account):
        return 1
    if _is_cashflow_center(account):
        return 2

    kind = str(account.get("account_kind") or account.get("type") or "")
    parent = str(account.get("parent_account_id") or account.get("parent_key") or "").strip()

    if bool(account.get("is_dependent_account")) or parent:
        return 3

    # Wallet accounts such as PayPal may exist without a saved parent after older
    # migrations or manual edits. They are still user-facing level-3 accounts,
    # not technical buckets, so keep them visible in selectors and All Conti.
    if kind in {"dependent_wallet", "wallet_balance"}:
        return 3

    if _is_financial_center(account):
        return 1
    return 0


def account_level_label(account: Mapping[str, Any]) -> str:
    level = account_level(account)
    if level == 1:
        return "Independent account"
    if level == 2:
        return "CashFlow"
    if level == 3:
        return "Dependent account"
    return "Technical / archived"


def _balance_account_ids_for_resolved(resolved: Mapping[str, Any]) -> list[str]:
    ids = list(resolved.get("balance_account_ids") or [])
    if ids:
        return ids
    return list(resolved.get("included_account_ids") or [])

def _accounts_by_id(user_id: str | None = None, include_archived: bool = True) -> dict[str, dict[str, Any]]:
    return {_account_id(account): dict(account) for account in all_accounts(user_id=user_id, include_archived=include_archived, include_main=True)}


def _method_rows(user_id: str | None = None, include_archived: bool = True) -> list[dict[str, Any]]:
    try:
        from money_manager.services.payment_method_service import all_payment_methods

        return [dict(row) for row in all_payment_methods(include_archived=include_archived, user_id=user_id)]
    except Exception:
        return []


def _method_by_id(user_id: str | None = None, include_archived: bool = True) -> dict[str, dict[str, Any]]:
    return {str(method.get("id") or ""): method for method in _method_rows(user_id=user_id, include_archived=include_archived)}


def financial_centers(user_id: str | None = None, include_archived: bool = False) -> list[dict[str, Any]]:
    centers: list[dict[str, Any]] = []
    for account in all_accounts(user_id=user_id, include_archived=True, include_main=True):
        if not _is_active(account, include_archived=include_archived):
            continue
        if _is_financial_center(account):
            centers.append(dict(account))
    return sorted(centers, key=lambda item: (int(float(item.get("display_order") or 1000)), str(item.get("label") or item.get("name") or "")))


def current_account_centers(user_id: str | None = None, include_archived: bool = False) -> list[dict[str, Any]]:
    return [account for account in financial_centers(user_id=user_id, include_archived=include_archived) if account.get("is_current_account") or account.get("account_kind") == "current_account"]


def independent_liquid_centers(user_id: str | None = None, include_archived: bool = False) -> list[dict[str, Any]]:
    return [
        account
        for account in financial_centers(user_id=user_id, include_archived=include_archived)
        if _is_liquid_account(account) and not (account.get("is_current_account") or account.get("account_kind") == "current_account")
    ]


def scope_selectable_accounts(user_id: str | None = None, include_archived: bool = False) -> list[dict[str, Any]]:
    """Accounts that can be selected/opened as their own UI scope.

    Financial centers are intentionally limited to avoid global double-counting.
    Scope selectors are different: the user must still be able to open dependent
    wallets such as PayPal, Glovo or EasyPark and inspect only their rows.

    Hidden card implementation balances are excluded here because prepaid-card
    balances are managed from the parent Conto card list, not as normal wallets.
    """
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for account in all_accounts(user_id=user_id, include_archived=True, include_main=True):
        key = _account_id(account)
        if not key or key in seen:
            continue
        if not _is_active(account, include_archived=include_archived):
            continue
        if _is_technical_account(account) or not _is_liquid_account(account):
            continue

        kind = str(account.get("account_kind") or account.get("type") or "")
        parent = str(account.get("parent_account_id") or account.get("parent_key") or "").strip()
        if parent and kind == "prepaid_balance":
            # Hidden implementation account for one prepaid card.
            continue

        rows.append(dict(account))
        seen.add(key)

    return sorted(
        rows,
        key=lambda item: (
            account_level(item) if account_level(item) > 0 else 99,
            int(float(item.get("display_order") or 1000)),
            str(item.get("label") or item.get("name") or ""),
        ),
    )


def dependent_accounts_for(parent_account_id: str, user_id: str | None = None, include_archived: bool = False) -> list[dict[str, Any]]:
    parent_key = normalize_account_key(parent_account_id, user_id=user_id)
    rows: list[dict[str, Any]] = []
    for account in all_accounts(user_id=user_id, include_archived=True, include_main=True):
        if not _is_active(account, include_archived=include_archived):
            continue
        if str(account.get("parent_account_id") or account.get("parent_key") or "") == parent_key:
            rows.append(dict(account))
    return sorted(rows, key=lambda item: (int(float(item.get("display_order") or 1000)), str(item.get("label") or "")))


def _method_account_ids(
    method: Mapping[str, Any],
    by_method: dict[str, Mapping[str, Any]],
    *,
    user_id: str | None = None,
    include_delegated_routes: bool = False,
    include_parent_card_owner: bool = True,
    _seen: set[str] | None = None,
) -> set[str]:
    ids = {
        str(method.get("linked_account_id") or "").strip(),
        str(method.get("funding_account_id") or "").strip(),
        str(method.get("settlement_account_id") or "").strip(),
        str(method.get("liability_account_id") or "").strip(),
        str(method.get("parent_account_id") or "").strip(),
    }
    ids.discard("")

    # A prepaid card can own a hidden stored-balance child account but still be
    # managed from the parent current account card list.  Do not apply this
    # parent roll-up to normal wallets such as PayPal; those must stay visible
    # only on their own wallet account.
    method_type = str(method.get("method_type") or "")
    if include_parent_card_owner and method_type == "prepaid_card":
        for account_id in list(ids):
            try:
                account = account_by_key(account_id, user_id=user_id, include_archived=True) or {}
            except Exception:
                account = {}
            parent = str(account.get("parent_account_id") or account.get("parent_key") or "").strip()
            if parent:
                ids.add(parent)

    if include_delegated_routes and str(method.get("settlement_mode") or "") == "delegated":
        seen = set(_seen or set())
        method_id = str(method.get("id") or "")
        delegate_id = str(method.get("delegates_to_payment_method_id") or "")
        if delegate_id and delegate_id not in seen and delegate_id in by_method:
            seen.add(method_id)
            ids.update(_method_account_ids(
                by_method[delegate_id],
                by_method,
                user_id=user_id,
                include_delegated_routes=True,
                include_parent_card_owner=include_parent_card_owner,
                _seen=seen,
            ))
    return ids


def _method_owner_account_ids(
    method: Mapping[str, Any],
    *,
    user_id: str | None = None,
) -> set[str]:
    """Accounts that should list/manage this payment method in the UI.

    This is intentionally stricter than route matching. A PayPal wrapper funded
    by a Main-bank debit card belongs to PayPal in the wallet UI, even though
    the underlying money route eventually touches Main.
    """
    method_type = str(method.get("method_type") or "")
    linked = str(method.get("linked_account_id") or "").strip()
    parent = str(method.get("parent_account_id") or "").strip()

    if method_type == "wallet_linked_card":
        return {value for value in {linked or parent} if value}

    if method_type == "prepaid_card":
        ids = {value for value in {linked, parent} if value}
        for account_id in list(ids):
            try:
                account = account_by_key(account_id, user_id=user_id, include_archived=True) or {}
            except Exception:
                account = {}
            account_parent = str(account.get("parent_account_id") or account.get("parent_key") or "").strip()
            if account_parent:
                ids.add(account_parent)
        return ids

    if method_type == "credit_card":
        ids = {value for value in {linked, parent, str(method.get("funding_account_id") or "").strip(), str(method.get("settlement_account_id") or "").strip()} if value}
        # Never make the hidden liability bucket the visible owner of the card.
        return {account_id for account_id in ids if account_id != str(method.get("liability_account_id") or "").strip()}

    return {
        value
        for value in {
            linked,
            parent,
            str(method.get("funding_account_id") or "").strip(),
            str(method.get("settlement_account_id") or "").strip(),
        }
        if value
    }


def payment_methods_for_account(
    account_id: str,
    user_id: str | None = None,
    include_archived: bool = False,
    *,
    include_delegated_routes: bool = False,
    ownership_only: bool = True,
) -> list[dict[str, Any]]:
    key = normalize_account_key(account_id, user_id=user_id)
    by_method = _method_by_id(user_id=user_id, include_archived=include_archived)
    result: list[dict[str, Any]] = []
    for method in by_method.values():
        if not include_archived and (method.get("is_archived") or not method.get("is_active", True)):
            continue
        account_ids = (
            _method_owner_account_ids(method, user_id=user_id)
            if ownership_only
            else _method_account_ids(method, by_method, user_id=user_id, include_delegated_routes=include_delegated_routes)
        )
        if key in account_ids:
            result.append(dict(method))
    return sorted(result, key=lambda item: (int(float(item.get("display_order") or 1000)), str(item.get("name") or "")))


def cards_for_account(
    account_id: str,
    user_id: str | None = None,
    include_archived: bool = True,
) -> list[dict[str, Any]]:
    key = normalize_account_key(account_id, user_id=user_id)
    cards: list[dict[str, Any]] = []

    for method in payment_methods_for_account(key, user_id=user_id, include_archived=include_archived):
        method_type = str(method.get("method_type") or "")

        if (
            method_type == "wallet_linked_card"
            and str(method.get("linked_account_id") or "") != key
        ):
            continue

        if method_type in {"debit_card", "credit_card", "prepaid_card", "wallet_linked_card"}:
            cards.append({**method, "source": "payment_method"})

    return cards


def resolve_account_scope(scope: str | Mapping[str, Any] | None = None, account_id: str | None = None, user_id: str | None = None) -> dict[str, Any]:
    if isinstance(scope, Mapping):
        raw_scope = str(scope.get("scope") or "")
        if raw_scope:
            scope = raw_scope
    scope_text = str(scope or "").strip()
    if not scope_text and account_id:
        scope_text = f"{SCOPE_ACCOUNT_PREFIX}{account_id}"
    if not scope_text:
        scope_text = SCOPE_GLOBAL

    accounts_by_id = _accounts_by_id(user_id=user_id, include_archived=True)

    if scope_text == SCOPE_GLOBAL:
        center_ids = [_account_id(account) for account in financial_centers(user_id=user_id, include_archived=False)]
        included: list[str] = []
        dependent: list[str] = []
        # Global visibility includes every active non-technical account so search,
        # transactions and lists really mean "all user accounts".  Global net,
        # however, is calculated only from financial centers to avoid double
        # counting dependent wallets such as PayPal when they are paid through a
        # linked bank card.
        for account in all_accounts(user_id=user_id, include_archived=False, include_main=True):
            account_id = _account_id(account)
            if not account_id or _is_technical_account(account):
                continue
            if account_id not in included:
                included.append(account_id)
            if bool(account.get("is_dependent_account")) or str(account.get("parent_account_id") or account.get("parent_key") or ""):
                dependent.append(account_id)
        return {
            "kind": "global",
            "scope": SCOPE_GLOBAL,
            "account_id": "",
            "label": "All Conti",
            "financial_center_ids": center_ids,
            "balance_account_ids": center_ids,
            "included_account_ids": included,
            "dependent_account_ids": sorted(set(dependent)),
            "is_global": True,
            "is_account": False,
        }

    if scope_text.startswith(SCOPE_ACCOUNT_PREFIX):
        raw_id = scope_text[len(SCOPE_ACCOUNT_PREFIX):]
    else:
        raw_id = account_id or scope_text
    key = normalize_account_key(raw_id, user_id=user_id)
    account = accounts_by_id.get(key)
    if not account:
        return resolve_account_scope(SCOPE_GLOBAL, user_id=user_id)

    included = [key]
    dependent_ids: list[str] = []
    if not bool(account.get("is_dependent_account")):
        for dep in dependent_accounts_for(key, user_id=user_id, include_archived=False):
            dep_id = _account_id(dep)
            dependent_ids.append(dep_id)
            included.append(dep_id)

    return {
        "kind": "account",
        "scope": f"{SCOPE_ACCOUNT_PREFIX}{key}",
        "account_id": key,
        "label": str(account.get("label") or account.get("name") or key),
        "financial_center_ids": [key] if _is_financial_center(account) else [],
        # Account pages show transactions from the selected account and its
        # dependent wallets, but the headline net remains the selected account's
        # own balance.  This is what makes PayPal-via-Bank1 visible in both places
        # without turning the model back into Main Account + everything else.
        "balance_account_ids": [key],
        "included_account_ids": list(dict.fromkeys(included)),
        "dependent_account_ids": list(dict.fromkeys(dependent_ids)),
        "is_global": False,
        "is_account": True,
    }


def scope_key(scope: str | Mapping[str, Any] | None) -> str:
    return resolve_account_scope(scope).get("scope", SCOPE_GLOBAL)


def accounts_for_scope(scope: str | Mapping[str, Any] | None, user_id: str | None = None) -> list[dict[str, Any]]:
    resolved = resolve_account_scope(scope, user_id=user_id)
    by_id = _accounts_by_id(user_id=user_id, include_archived=True)
    return [by_id[key] for key in resolved.get("included_account_ids", []) if key in by_id]


def _ensure_enriched(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None:
        return pd.DataFrame()
    if df.empty:
        return df.copy()
    if "account_key" not in df.columns or "account_signed_amount" not in df.columns:
        from money_manager.services.account_service import enrich_transactions_with_accounts

        return enrich_transactions_with_accounts(df)
    return df.copy()


def _load_enriched_transactions() -> pd.DataFrame:
    try:
        from money_manager.services.transaction_service import load_transactions

        return _ensure_enriched(load_transactions())
    except Exception:
        return pd.DataFrame()


def transactions_for_scope(df: pd.DataFrame | None, scope: str | Mapping[str, Any] | None, user_id: str | None = None) -> pd.DataFrame:
    data = _ensure_enriched(df)
    if data.empty:
        return data.copy()
    resolved = resolve_account_scope(scope, user_id=user_id)
    included = set(resolved.get("included_account_ids") or [])
    if not included:
        return data.iloc[0:0].copy()

    mask = pd.Series(False, index=data.index)
    for column in ["account_key", "account_id", "account_key_snapshot", "settlement_account_id_snapshot", "funding_account_id_snapshot", "liability_account_id_snapshot"]:
        if column in data.columns:
            mask = mask | data[column].fillna("").astype(str).isin(included)

    # Also match by payment method. This is what makes a PayPal transaction paid
    # through a Bank1 card show up both in PayPal and in Bank1's scoped log.
    payment_columns = [column for column in ["payment_method_id", "payment_method_id_snapshot"] if column in data.columns]
    if payment_columns:
        by_method = _method_by_id(user_id=user_id, include_archived=True)
        method_scope_cache: dict[str, bool] = {}
        def _method_hits_scope(value: Any) -> bool:
            method_id = str(value or "").strip()
            if not method_id:
                return False
            if method_id not in method_scope_cache:
                method = by_method.get(method_id)
                method_scope_cache[method_id] = bool(method and (_method_account_ids(method, by_method, user_id=user_id) & included))
            return method_scope_cache[method_id]
        method_mask = pd.Series(False, index=data.index)
        for column in payment_columns:
            method_mask = method_mask | data[column].map(_method_hits_scope).fillna(False)
        mask = mask | method_mask

    result = data[mask].copy()
    if "date" in result.columns:
        result = result.sort_values(by=["date"], ascending=False)
    return result


def _ledger_rows_for_scope(scope: str | Mapping[str, Any] | None, user_id: str | None = None) -> list[dict[str, Any]]:
    resolved = resolve_account_scope(scope, user_id=user_id)
    included = set(resolved.get("included_account_ids") or [])
    if not included:
        return []
    try:
        from money_manager.repositories.account_ledger import read_ledger_rows

        rows = read_ledger_rows(user_id=user_id)
    except Exception:
        return []
    return [row for row in rows if str(row.get("account_id") or "") in included and str(row.get("is_void") or "").lower() not in {"1", "true", "yes"}]


def ledger_movements_for_scope(scope: str | Mapping[str, Any] | None, user_id: str | None = None) -> list[dict[str, Any]]:
    return _ledger_rows_for_scope(scope, user_id=user_id)


def _initial_balance(account_id: str, user_id: str | None = None) -> float:
    account = account_by_key(account_id, user_id=user_id, include_archived=True)
    if not account or not _is_liquid_account(account):
        return 0.0
    try:
        return float(account.get("initial_balance") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _ledger_is_authoritative(user_id: str | None = None) -> bool:
    try:
        from money_manager.config.user_paths import get_user_data_dir
        import json

        path = get_user_data_dir(user_id) / "migration_info.json"

        if not path.exists():
            return False

        payload = json.loads(path.read_text(encoding="utf-8"))
        ledger_info = payload.get("ledger_migration", {})

        return bool(
            ledger_info.get("backfilled") is True
            and ledger_info.get("authoritative") is True
        )
    except Exception:
        return False

def _ledger_balance_for_account(account_id: str, user_id: str | None = None) -> float | None:
    if not _ledger_is_authoritative(user_id=user_id):
        return None

    # existing ledger loading logic here


def _transaction_balance_for_account(
    account_id: str,
    user_id: str | None = None,
    df: pd.DataFrame | None = None,
) -> float:
    data = _ensure_enriched(df) if df is not None else _load_enriched_transactions()

    account_key = normalize_account_key(account_id, user_id=user_id)

    if account_key == MAIN_ACCOUNT_KEY:
        try:
            from money_manager.services.account_service import main_account_transactions

            main_rows = main_account_transactions(data)
            if not main_rows.empty and "signed_amount" in main_rows.columns:
                return float(
                    pd.to_numeric(main_rows["signed_amount"], errors="coerce")
                    .fillna(0.0)
                    .sum()
                )
        except Exception:
            return 0.0
        return 0.0

    if data.empty:
        transaction_total = 0.0
    elif "account_key" in data.columns:
        sub = data[data["account_key"].astype(str) == account_key]
        amount_column = "account_signed_amount" if "account_signed_amount" in sub.columns else "signed_amount"
        transaction_total = float(
            pd.to_numeric(sub.get(amount_column, pd.Series(dtype=float)), errors="coerce")
            .fillna(0.0)
            .sum()
        )
    elif "account_id" in data.columns:
        sub = data[data["account_id"].astype(str) == account_key]
        transaction_total = float(
            pd.to_numeric(sub.get("signed_amount", pd.Series(dtype=float)), errors="coerce")
            .fillna(0.0)
            .sum()
        )
    else:
        transaction_total = 0.0

    # Internal transfers are still stored separately while the app is in the CSV →
    # ledger migration period.  Add their synthetic account movements for non-main
    # accounts so top-ups, prepaid reloads and account-to-account movements are
    # reflected on the selected Conto without requiring the ledger to be globally
    # authoritative.
    transfer_total = 0.0
    try:
        from money_manager.services.internal_transfer_service import auxiliary_transfer_movements

        transfer_rows = auxiliary_transfer_movements(account_key=account_key)
        if not transfer_rows.empty and "account_signed_amount" in transfer_rows.columns:
            transfer_total = float(
                pd.to_numeric(transfer_rows["account_signed_amount"], errors="coerce")
                .fillna(0.0)
                .sum()
            )
    except Exception:
        transfer_total = 0.0

    return transaction_total + transfer_total


def net_balance_for_scope(
    scope: str | Mapping[str, Any] | None,
    user_id: str | None = None,
    df: pd.DataFrame | None = None,
) -> float:
    resolved = resolve_account_scope(scope, user_id=user_id)
    data = _ensure_enriched(df) if df is not None else None
    total = 0.0
    for account_id in _balance_account_ids_for_resolved(resolved):
        total += _initial_balance(account_id, user_id=user_id)
        ledger_total = _ledger_balance_for_account(account_id, user_id=user_id)
        total += ledger_total if ledger_total is not None else _transaction_balance_for_account(account_id, user_id=user_id, df=data)
    return round(float(total), 2)


def _row_account_candidates(row: Mapping[str, Any], user_id: str | None = None) -> set[str]:
    candidates: set[str] = set()
    for field in [
        "account_id",
        "account_key",
        "account_key_snapshot",
        "settlement_account_id",
        "funding_account_id",
        "liability_account_id",
        "settlement_account_id_snapshot",
        "funding_account_id_snapshot",
        "liability_account_id_snapshot",
    ]:
        value = str(row.get(field) or "").strip()
        if value:
            candidates.add(normalize_account_key(value, user_id=user_id))
    account_value = str(row.get("account") or "").strip()
    if account_value:
        candidates.add(normalize_account_key(account_value, user_id=user_id))
    method_id = str(row.get("payment_method_id") or row.get("preferred_payment_method_id") or "").strip()
    if method_id:
        by_method = _method_by_id(user_id=user_id, include_archived=True)
        method = by_method.get(method_id)
        if method:
            candidates.update(_method_account_ids(method, by_method, user_id=user_id))
    if not candidates:
        candidates.add(MAIN_ACCOUNT_KEY)
    return {candidate for candidate in candidates if candidate}


def _row_in_scope(row: Mapping[str, Any], scope: str | Mapping[str, Any] | None, user_id: str | None = None) -> bool:
    resolved = resolve_account_scope(scope, user_id=user_id)
    included = set(resolved.get("included_account_ids") or [])
    if not included:
        return False
    return bool(_row_account_candidates(row, user_id=user_id) & included)


def _amount(value: Any, allow_negative: bool = False) -> float:
    try:
        number = float(str(value or 0).replace(",", "."))
    except (TypeError, ValueError):
        number = 0.0
    return number if allow_negative else max(0.0, number)


def _planning_signed_amount(row: Mapping[str, Any], amount_field: str = "amount") -> float:
    amount = _amount(row.get(amount_field))
    row_type = str(row.get("type") or "expense").casefold()
    return -amount if row_type == "income" else amount


def pending_for_scope(scope: str | Mapping[str, Any] | None, user_id: str | None = None) -> list[dict[str, Any]]:
    try:
        from money_manager.repositories.pending import load_pending

        rows = load_pending()
    except Exception:
        rows = []
    return pending_rows_for_scope(rows, scope, user_id=user_id)


def pending_rows_for_scope(rows: list[dict[str, Any]], scope: str | Mapping[str, Any] | None, user_id: str | None = None) -> list[dict[str, Any]]:
    return [dict(row) for row in rows if _row_in_scope(row, scope, user_id=user_id)]


def pending_total_for_scope(scope: str | Mapping[str, Any] | None, user_id: str | None = None) -> float:
    total = 0.0
    for row in pending_for_scope(scope, user_id=user_id):
        if str(row.get("status") or "pending").casefold() != "pending":
            continue
        total += _planning_signed_amount(row)
    return round(float(total), 2)


def pending_context_for_scope(scope: str | Mapping[str, Any] | None, user_id: str | None = None) -> dict[str, Any]:
    rows = pending_for_scope(scope, user_id=user_id)
    try:
        from money_manager.services.pending_service import prepare_pending_for_display

        ctx = prepare_pending_for_display(rows)
    except Exception:
        ctx = {"all": rows, "pending": rows, "executed": [], "pending_total": pending_total_for_scope(scope, user_id=user_id)}
    ctx["scope"] = resolve_account_scope(scope, user_id=user_id)
    ctx["scope_pending_total"] = pending_total_for_scope(scope, user_id=user_id)
    ctx["main_pending_total"] = ctx["scope_pending_total"]
    return ctx


def recurring_for_scope(scope: str | Mapping[str, Any] | None, user_id: str | None = None) -> list[dict[str, Any]]:
    try:
        from money_manager.repositories.recurring import load_recurring

        rows = load_recurring()
    except Exception:
        rows = []
    return recurring_rows_for_scope(rows, scope, user_id=user_id)


def recurring_rows_for_scope(rows: list[dict[str, Any]], scope: str | Mapping[str, Any] | None, user_id: str | None = None) -> list[dict[str, Any]]:
    return [dict(row) for row in rows if _row_in_scope(row, scope, user_id=user_id)]


def recurring_monthly_total_for_scope(scope: str | Mapping[str, Any] | None, user_id: str | None = None) -> float:
    total = 0.0
    for row in recurring_for_scope(scope, user_id=user_id):
        try:
            from money_manager.services.recurring_service import is_rule_finished, parse_frequency_months

            if is_rule_finished(row):
                continue
            frequency = max(1, parse_frequency_months(row.get("frequency")))
        except Exception:
            frequency = max(1, int(_amount(row.get("frequency") or 1)))
        total += _planning_signed_amount(row) / frequency
    return round(float(total), 2)


def recurring_context_for_scope(scope: str | Mapping[str, Any] | None, user_id: str | None = None) -> dict[str, Any]:
    rows = recurring_for_scope(scope, user_id=user_id)
    try:
        from money_manager.services.recurring_service import prepare_recurring_sections

        ctx = prepare_recurring_sections(rows)
    except Exception:
        ctx = {"all": rows, "active": rows, "finished": []}
    ctx["scope"] = resolve_account_scope(scope, user_id=user_id)
    ctx["recurring_monthly_total"] = recurring_monthly_total_for_scope(scope, user_id=user_id)
    return ctx


def payables_for_scope(scope: str | Mapping[str, Any] | None, user_id: str | None = None) -> list[dict[str, Any]]:
    try:
        from money_manager.repositories.payables import load_payables

        rows = load_payables()
    except Exception:
        rows = []
    return payable_rows_for_scope(rows, scope, user_id=user_id)


def payable_rows_for_scope(rows: list[dict[str, Any]], scope: str | Mapping[str, Any] | None, user_id: str | None = None) -> list[dict[str, Any]]:
    return [dict(row) for row in rows if _row_in_scope(row, scope, user_id=user_id)]


def payables_total_for_scope(scope: str | Mapping[str, Any] | None, user_id: str | None = None) -> float:
    total = 0.0
    for row in payables_for_scope(scope, user_id=user_id):
        if str(row.get("status") or "active").casefold() != "active":
            continue
        total += _amount(row.get("remaining_amount"))
    return round(float(total), 2)


def payables_context_for_scope(scope: str | Mapping[str, Any] | None, user_id: str | None = None) -> dict[str, Any]:
    rows = payables_for_scope(scope, user_id=user_id)
    active = [row for row in rows if str(row.get("status") or "active").casefold() == "active" and _amount(row.get("remaining_amount")) > 0]
    original_total = sum(_amount(row.get("original_amount")) for row in rows)
    active_remaining = sum(_amount(row.get("remaining_amount")) for row in active)
    paid_total = sum(max(0.0, _amount(row.get("original_amount")) - _amount(row.get("remaining_amount"))) for row in rows)
    return {
        "payables": rows,
        "active_payables": active,
        "totals": {
            "active_remaining": float(active_remaining),
            "main_remaining": float(active_remaining),
            "auxiliary_remaining": 0.0,
            "original_total": float(original_total),
            "paid_total": float(paid_total),
            "count_active": len(active),
            "count_total": len(rows),
        },
        "scope": resolve_account_scope(scope, user_id=user_id),
    }

def debts_for_scope(scope: str | Mapping[str, Any] | None, user_id: str | None = None) -> list[dict[str, Any]]:
    try:
        from money_manager.repositories.debts import load_debts

        rows = load_debts()
    except Exception:
        rows = []
    return [dict(row) for row in rows if _row_in_scope(row, scope, user_id=user_id)]


def receivables_for_scope(scope: str | Mapping[str, Any] | None, user_id: str | None = None) -> list[dict[str, Any]]:
    try:
        from money_manager.repositories.receivables import load_receivables

        rows = load_receivables()
    except Exception:
        rows = []
    return [dict(row) for row in rows if _row_in_scope(row, scope, user_id=user_id)]


def net_after_pending_for_scope(scope: str | Mapping[str, Any] | None, user_id: str | None = None, df: pd.DataFrame | None = None) -> float:
    return round(net_balance_for_scope(scope, user_id=user_id, df=df) - pending_total_for_scope(scope, user_id=user_id), 2)


def net_after_payables_for_scope(scope: str | Mapping[str, Any] | None, user_id: str | None = None, df: pd.DataFrame | None = None) -> float:
    return round(net_balance_for_scope(scope, user_id=user_id, df=df) - payables_total_for_scope(scope, user_id=user_id), 2)


def projected_net_for_scope(scope: str | Mapping[str, Any] | None, user_id: str | None = None, df: pd.DataFrame | None = None) -> float:
    return round(
        net_balance_for_scope(scope, user_id=user_id, df=df)
        - pending_total_for_scope(scope, user_id=user_id)
        - payables_total_for_scope(scope, user_id=user_id)
        - recurring_monthly_total_for_scope(scope, user_id=user_id),
        2,
    )


def scope_balance_summary(
    scope: str | Mapping[str, Any] | None,
    user_id: str | None = None,
    df: pd.DataFrame | None = None,
) -> dict[str, Any]:
    resolved = resolve_account_scope(scope, user_id=user_id)
    data = _ensure_enriched(df) if df is not None else _load_enriched_transactions()
    net = net_balance_for_scope(resolved, user_id=user_id, df=data)
    pending = pending_total_for_scope(resolved, user_id=user_id)
    payables = payables_total_for_scope(resolved, user_id=user_id)
    recurring = recurring_monthly_total_for_scope(resolved, user_id=user_id)
    account_id = resolved.get("account_id", "")
    try:
        tx_count = int(len(transactions_for_scope(data, resolved, user_id=user_id)))
    except Exception:
        tx_count = 0
    methods_count = len(payment_methods_for_account(account_id, user_id=user_id, include_archived=False)) if account_id else len(_method_rows(user_id=user_id, include_archived=False))
    return {
        "scope": resolved["scope"],
        "kind": resolved["kind"],
        "account_id": account_id,
        "label": resolved["label"],
        "net_balance": net,
        "balance": net,
        "pending_total": pending,
        "payables_total": payables,
        "recurring_monthly_total": recurring,
        "net_after_pending": round(net - pending, 2),
        "net_after_payables": round(net - payables, 2),
        "projected_net": round(net - pending - payables - recurring, 2),
        "transactions_count": tx_count,
        "dependent_accounts_count": len(resolved.get("dependent_account_ids", [])),
        "payment_methods_count": methods_count,
        "dependent_accounts": [account for dep_id in resolved.get("dependent_account_ids", []) if (account := account_by_key(dep_id, user_id=user_id, include_archived=True))],
        "payment_methods": payment_methods_for_account(account_id, user_id=user_id, include_archived=False) if account_id else [],
        **resolved,
    }


def all_financial_center_summaries(user_id: str | None = None, df: pd.DataFrame | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    data = _ensure_enriched(df) if df is not None else _load_enriched_transactions()
    for center in financial_centers(user_id=user_id, include_archived=False):
        center_id = _account_id(center)
        summary = scope_balance_summary(f"account:{center_id}", user_id=user_id, df=data)
        summary.update({
            "account_id": center_id,
            "key": center_id,
            "account_kind": center.get("account_kind"),
            "account_level": account_level(center),
            "account_level_label": account_level_label(center),
            "is_current_account": bool(center.get("is_current_account")),
            "is_dependent_account": bool(center.get("is_dependent_account")),
            "is_cashflow_account": _is_cashflow_center(center),
        })
        rows.append(summary)
    return rows


def global_balance_summary(user_id: str | None = None, df: pd.DataFrame | None = None) -> dict[str, Any]:
    return scope_balance_summary(SCOPE_GLOBAL, user_id=user_id, df=df)


def dashboard_context_for_scope(df: pd.DataFrame, scope: str | Mapping[str, Any] | None, user_id: str | None = None) -> dict[str, Any]:
    resolved = resolve_account_scope(scope, user_id=user_id)
    data = _ensure_enriched(df)
    return {
        "selected_scope": resolved,
        "selected_scope_key": resolved["scope"],
        "scope_label": resolved["label"],
        "scope_is_global": resolved["is_global"],
        "scope_is_account": resolved["is_account"],
        "scope_summary": scope_balance_summary(resolved, user_id=user_id, df=data),
        "transactions": transactions_for_scope(data, resolved, user_id=user_id),
    }


def analysis_context_for_scope(df: pd.DataFrame, scope: str | Mapping[str, Any] | None, user_id: str | None = None) -> dict[str, Any]:
    return dashboard_context_for_scope(df, scope, user_id=user_id)


def scope_options(user_id: str | None = None) -> list[dict[str, Any]]:
    options = [
        {
            "value": SCOPE_GLOBAL,
            "label": "All Conti",
            "scope": SCOPE_GLOBAL,
            "is_global": True,
        }
    ]

    for account in scope_selectable_accounts(user_id=user_id, include_archived=False):
        key = _account_id(account)
        if not key:
            continue

        label = str(account.get("label") or account.get("name") or key)
        parent_key = str(account.get("parent_account_id") or account.get("parent_key") or "").strip()
        if parent_key:
            parent_label = account_label_for_key(parent_key, user_id=user_id)
            if parent_label:
                label = f"{parent_label} / {label}"

        options.append(
            {
                "value": f"account:{key}",
                "label": label,
                "scope": f"account:{key}",
                "account_id": key,
                "is_global": False,
                "account_level": account_level(account),
                "account_kind": str(account.get("account_kind") or account.get("type") or ""),
            }
        )

    return options
