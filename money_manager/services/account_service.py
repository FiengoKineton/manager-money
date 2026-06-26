from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from money_manager.config import (
    CREDIT_CARD_PAYMENT_CATEGORY,
    MAIN_ACCOUNT_KEY,
    MAIN_NET_AFFECTS,
    MAIN_NET_CREDIT_PENDING,
    MAIN_NET_SEPARATE,
    PAYPAL_ACCOUNT_KEY,
    PAYPAL_CREDIT_ALIASES,
    account_description_for_key,
    account_label_for_key,
    account_options_for_analysis,
    account_policy_for_key,
    account_parent_key,
    auxiliary_account_keys,
    category_aliases_by_key,
    normalize_account_key,
    is_main_account_value,
)
from money_manager.services.account_config_service import (
    add_card_to_account,
    archive_account,
    archive_card,
    account_by_key,
    create_account_from_form as create_config_account_from_form,
    restore_account,
    update_account_from_form,
    all_accounts,
    slugify,
)


# Category/account aliases are loaded dynamically from the built-in accounts and the current user accounts.json.



@dataclass(frozen=True)
class AccountInference:
    key: str
    source: str


DEFAULT_CREDIT_ACCOUNT_KEY = "credit_card"
PAYPAL_MAIN_BANK_LINK_ALIASES = {
    "paypal card",
    "pay pal card",
    "paypal debit",
    "paypal bank",
    "paypal main",
    "paypal linked card",
    "paypal linked debit",
}
PAYPAL_CREDIT_ROUTE_ALIASES = set(PAYPAL_CREDIT_ALIASES) - PAYPAL_MAIN_BANK_LINK_ALIASES


def enrich_transactions_with_accounts(df: pd.DataFrame) -> pd.DataFrame:
    """Add normalized account columns without changing the original CSV value.

    Explicit values in the CSV ``account`` column have priority.  If that field
    is empty, configured category aliases are also routed to the matching
    account as shadow/category-inferred movements.  This keeps the old CSV workflow
    but fixes cases where top-ups were stored as an expense category rather than
    as an account value.
    """
    df = df.copy()
    for column in [
        "account_key",
        "account_label",
        "is_auxiliary_account",
        "affects_main_net",
        "account_route_source",
        "account_signed_amount",
    ]:
        if df.empty:
            df[column] = []

    if df.empty:
        return df

    if "account" not in df.columns:
        df["account"] = ""
    if "category" not in df.columns:
        df["category"] = ""
    if "sub_category" not in df.columns:
        df["sub_category"] = ""
    if "description" not in df.columns:
        df["description"] = ""

    df["account"] = df["account"].fillna("")

    category_lookup, category_search = _category_alias_lookup()
    policies = _account_policy_lookup()
    labels = _account_label_lookup()

    inferences = df.apply(
        lambda row: _infer_account_from_row_cached(row, category_lookup, category_search),
        axis=1,
    )
    df["account_key"] = [inference.key for inference in inferences]
    df["account_route_source"] = [inference.source for inference in inferences]
    df["account_label"] = df["account_key"].map(lambda key: labels.get(str(key), account_label_for_key(key)))
    df["is_auxiliary_account"] = df["account_key"].isin(auxiliary_account_keys())
    df["affects_main_net"] = _affects_main_net_mask(df)
    df["account_signed_amount"] = df.apply(lambda row: _account_signed_amount_cached(row, policies), axis=1)
    return df


def main_account_transactions(df: pd.DataFrame) -> pd.DataFrame:
    """Transactions that affect the main bank/net balance.

    The net balance is intentionally conservative now: it includes only rows
    whose raw CSV ``account`` field is blank or explicitly points to the main
    route (Main bank account, credit route, or their aliases).

    Rows explicitly assigned to accounts with ``separate_when_explicit`` are
    excluded from the main net and analysed in the account page. Blank-account
    category matches can still build that account balance, but they do not remove
    the original row from the main net. This is important for top-ups: money can
    leave the main route and also become available in a separate account.

    Rows with missing or invalid dates are ignored for balance calculations. A
    corrupted date such as ``0012-04-14`` should not reduce the current net just
    because the app is now calculating from full CSV history instead of only the
    visible year-to-date period.
    """
    if df.empty:
        try:
            from money_manager.services.internal_transfer_service import main_account_transfer_movements
            return main_account_transfer_movements().copy()
        except Exception:
            return df.copy()
    if "account_key" not in df.columns:
        df = enrich_transactions_with_accounts(df)
    df = _valid_dated_transactions(df)
    main_rows = df[_affects_main_net_mask(df)].copy()

    # Internal transfers affect the main-bank position but are not income or
    # expenses. They are synthetic rows with type="transfer", so summaries add
    # them to net while keeping income/expense totals clean.
    try:
        from money_manager.services.internal_transfer_service import main_account_transfer_movements
        transfer_rows = main_account_transfer_movements()
    except Exception:
        transfer_rows = pd.DataFrame()

    if not transfer_rows.empty:
        main_rows = pd.concat([main_rows, transfer_rows], ignore_index=True, sort=False)
        if "date" in main_rows.columns:
            main_rows = main_rows.sort_values(by=["date"], ascending=False)
    return main_rows.copy()




def _valid_dated_transactions(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only rows that have a usable transaction date for money-position math.

    ``load_all`` already parses dates with ``errors="coerce"``. Broken CSV
    values become ``NaT``. Those rows can still exist in the raw transaction log,
    but they should not affect balances, account totals, or availability.
    """
    if df.empty or "date" not in df.columns:
        return df.copy()
    return df[df["date"].notna()].copy()


def _category_alias_lookup() -> tuple[dict[str, str], list[tuple[str, str]]]:
    alias_map = category_aliases_by_key()
    lookup: dict[str, str] = {}
    search: list[tuple[str, str]] = []
    for key, aliases in alias_map.items():
        for alias in aliases:
            cleaned = _clean_text(alias)
            if not cleaned:
                continue
            lookup[cleaned] = key
            search.append((key, cleaned))
    search.sort(key=lambda item: len(item[1]), reverse=True)
    return lookup, search


def _account_label_lookup() -> dict[str, str]:
    labels = {MAIN_ACCOUNT_KEY: account_label_for_key(MAIN_ACCOUNT_KEY)}
    try:
        for account in all_accounts(include_archived=True, include_main=True):
            key = str(account.get("key") or account.get("id") or "")
            if key:
                labels[key] = str(account.get("label") or account.get("name") or account_label_for_key(key))
    except Exception:
        pass
    return labels


def _account_policy_lookup() -> dict[str, str]:
    policies = {MAIN_ACCOUNT_KEY: MAIN_NET_AFFECTS}
    try:
        for account in all_accounts(include_archived=True, include_main=True):
            key = str(account.get("key") or account.get("id") or "")
            if key:
                policies[key] = str(account.get("main_net_policy") or MAIN_NET_SEPARATE)
    except Exception:
        pass
    return policies

def _affects_main_net_mask(df: pd.DataFrame) -> pd.Series:
    if df.empty:
        return pd.Series(dtype=bool, index=df.index)

    raw_account = df.get("account", pd.Series("", index=df.index)).fillna("").astype(str)
    raw_account_clean = raw_account.map(_clean_text)
    route_source = df.get("account_route_source", pd.Series("", index=df.index)).fillna("").astype(str)
    account_key = df.get("account_key", pd.Series(MAIN_ACCOUNT_KEY, index=df.index)).fillna(MAIN_ACCOUNT_KEY).astype(str)
    transaction_type = df.get("type", pd.Series("", index=df.index)).fillna("").astype(str).str.casefold()

    blank_account = raw_account_clean.eq("")
    explicit_main = raw_account_clean.ne("") & raw_account.map(is_main_account_value)
    category_shadow = route_source.eq("category_match")

    policy_lookup = _account_policy_lookup()
    policies = account_key.map(lambda key: policy_lookup.get(str(key), account_policy_for_key(key)))
    policy_affects_main = policies.eq(MAIN_NET_AFFECTS)
    policy_credit_pending = policies.eq(MAIN_NET_CREDIT_PENDING)
    credit_settlement = policy_credit_pending & _credit_settlement_like_mask(df)
    credit_pending_charge = policy_credit_pending & ~credit_settlement

    separate_explicit = raw_account_clean.ne("") & account_key.isin(auxiliary_account_keys()) & policies.eq(MAIN_NET_SEPARATE)

    # Very important legacy compatibility: older FiengoKineton CSV rows used
    # account="Cash" as a payment-method note, not as a real separate-account
    # route. Keep those rows in the main net while still letting Cash Flow show
    # them in its account movement list. New forms now store stable account keys,
    # so a new custom account called Cash is not confused with this legacy value.
    legacy_cash_main = raw_account_clean.eq("cash")
    separate_explicit = separate_explicit & ~legacy_cash_main

    # Blank cleanup/reconciliation rows that infer an auxiliary account are balance
    # corrections for the auxiliary account only, not main-bank expenses.
    auxiliary_cleanup = account_key.isin(auxiliary_account_keys()) & _cleanup_like_mask(df)

    investment_main = transaction_type.eq("investment") & ~account_key.isin(auxiliary_account_keys())

    # Ordinary blank-account category matches keep affecting the main net for
    # legacy top-up/shadow accounts such as Cash Flow or Pre-paid. Credit-card
    # category matches are different: a blank-account row with category
    # "Credit cards" is a real credit-card charge, so it must wait for the
    # monthly statement instead of reducing main net immediately.
    affects = (
        (blank_account & ~credit_pending_charge)
        | explicit_main
        | legacy_cash_main
        | (category_shadow & ~credit_pending_charge)
        | policy_affects_main
        | credit_settlement
        | investment_main
    )
    affects = affects & ~separate_explicit & ~auxiliary_cleanup
    return affects

def auxiliary_account_transactions(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    if "account_key" not in df.columns:
        df = enrich_transactions_with_accounts(df)
    df = _valid_dated_transactions(df)
    return df[df["account_key"].isin(auxiliary_account_keys())].copy()


def account_movements(
    df: pd.DataFrame,
    account_key: str | None = None,
    include_sparagnat_cash: bool = True,
) -> pd.DataFrame:
    """Return movements from the point of view of the separate liquid accounts.

    ``signed_amount`` keeps the original transaction sign used by the main app.
    ``account_signed_amount`` is the balance impact on the liquid account:
    income/top-ups are positive and actual spending from that account is
    negative.
    """
    if df.empty:
        df = enrich_transactions_with_accounts(df)
    elif "account_key" not in df.columns or "account_signed_amount" not in df.columns:
        df = enrich_transactions_with_accounts(df)

    df = _valid_dated_transactions(df)

    frames: list[pd.DataFrame] = []
    if not df.empty:
        tx = df[df["account_key"].isin(auxiliary_account_keys())].copy()
        if not tx.empty:
            tx["source"] = "transaction"
            tx["source_label"] = tx.apply(_source_label_for_transaction, axis=1)
            tx["source_url_kind"] = "transaction"
            tx["source_row_index"] = tx.index
            tx["display_signed_amount"] = tx["account_signed_amount"]
            paypal_link_mask = tx["account_route_source"].fillna("").eq("paypal_credit_link")
            if paypal_link_mask.any():
                tx.loc[paypal_link_mask, "source_label"] = "PayPal via credit card"
                tx.loc[paypal_link_mask, "display_signed_amount"] = -pd.to_numeric(tx.loc[paypal_link_mask, "amount"], errors="coerce").fillna(0.0).abs()
            tx["direction"] = tx["display_signed_amount"].map(lambda value: "in" if value >= 0 else "out")
            frames.append(tx)

        linked_paypal = _paypal_credit_linked_paypal_movements(df)
        if not linked_paypal.empty:
            frames.append(linked_paypal)

    try:
        from money_manager.services.internal_transfer_service import auxiliary_transfer_movements
        transfer_frame = auxiliary_transfer_movements(account_key=account_key)
    except Exception:
        transfer_frame = pd.DataFrame()
    if not transfer_frame.empty:
        frames.append(transfer_frame)

    if include_sparagnat_cash:
        sparagnat_frame = _sparagnat_cash_movements()
        if not sparagnat_frame.empty:
            frames.append(sparagnat_frame)

    if not frames:
        return _empty_account_movements()

    movements = pd.concat(frames, ignore_index=True, sort=False)
    movements["date"] = pd.to_datetime(movements["date"], errors="coerce")
    movements["amount"] = pd.to_numeric(movements["amount"], errors="coerce").fillna(0.0)
    movements["account_signed_amount"] = pd.to_numeric(
        movements["account_signed_amount"], errors="coerce"
    ).fillna(0.0)
    movements["direction"] = movements["account_signed_amount"].map(lambda value: "in" if value >= 0 else "out")
    movements["account_label"] = movements["account_key"].map(account_label_for_key)
    movements["is_auxiliary_account"] = True

    if account_key:
        movements = movements[movements["account_key"] == account_key].copy()

    if movements.empty:
        return _empty_account_movements()

    return movements.sort_values(by=["date"], ascending=False).reset_index(drop=True)


def account_balance_rows(df: pd.DataFrame) -> list[dict]:
    """Return one summary row for each configured non-main account."""
    movements = account_movements(df)
    rows: list[dict] = []

    for option in account_options_for_analysis():
        key = option["key"]
        sub = movements[movements["account_key"] == key] if not movements.empty else movements
        incoming = _sum_direction(sub, "in")
        outgoing = _sum_direction(sub, "out")
        initial_balance = _account_initial_balance(option)
        movement_balance = float(sub["account_signed_amount"].sum()) if not sub.empty else 0.0
        balance = initial_balance + movement_balance

        last_date = ""
        last_movement_label = "No movement yet"
        if not sub.empty and "date" in sub:
            valid_dates = sub["date"].dropna()
            if not valid_dates.empty:
                last = valid_dates.max()
                last_date = last.strftime("%Y-%m-%d")
                last_movement_label = f"Last movement: {last_date}"

        option_parent = option.get("parent_key", "")
        rows.append({
            "key": key,
            "label": account_label_for_key(key),
            "display_label": option.get("display_label") or account_label_for_key(key),
            "parent_key": option_parent,
            "is_other_child": option_parent == "other_account",
            "description": account_description_for_key(key),
            "initial_balance": initial_balance,
            "movement_balance": movement_balance,
            "main_net_policy": option.get("main_net_policy", MAIN_NET_SEPARATE),
            "is_active": option.get("is_active", True),
            "is_container": option.get("is_container", False),
            "cards": option.get("cards", []),
            "aliases": option.get("aliases", []),
            "category_aliases": option.get("category_aliases", []),
            "aliases_text": ", ".join(option.get("aliases", [])),
            "category_aliases_text": ", ".join(option.get("category_aliases", [])),
            "type": option.get("type", option.get("account_kind", "wallet_balance")),
            "account_kind": option.get("account_kind", option.get("type", "wallet_balance")),
            "currency": option.get("currency", "EUR"),
            "institution": option.get("institution", ""),
            "iban": option.get("iban", ""),
            "bic_swift": option.get("bic_swift", ""),
            "is_current_account": option.get("is_current_account", False),
            "is_dependent_account": option.get("is_dependent_account", False),
            "is_liability": option.get("is_liability", False),
            "is_closed": option.get("is_closed", False),
            "closed_at": option.get("closed_at", ""),
            "replacement_account_id": option.get("replacement_account_id", ""),
            "display_order": option.get("display_order", 100),
            "category_match_enabled": option.get("category_match_enabled", True),
            "category_match_mode": option.get("category_match_mode", "top_up_shadow"),
            "parent_account_id": option.get("parent_account_id") or option.get("parent_key") or "",
            "due_day": option.get("due_day", 15),
            "statement_day": option.get("statement_day", ""),
            "balance": balance,
            "income": incoming,
            "incoming": incoming,
            "expenses": outgoing,
            "outgoing": outgoing,
            "investments": _sum_type(sub, "investment"),
            "count": int(len(sub)),
            "income_count": int((sub["direction"] == "in").sum()) if not sub.empty else 0,
            "expense_count": int((sub["direction"] == "out").sum()) if not sub.empty else 0,
            "investment_count": int((sub.get("type", pd.Series(dtype=str)) == "investment").sum()) if not sub.empty else 0,
            "last_date": last_date,
            "last_movement_label": last_movement_label,
            "balance_tone": "positive" if balance >= 0 else "negative",
            "monthly_preview": _monthly_summary_for_account(sub, limit=4),
        })

    total_abs_balance = sum(abs(row["balance"]) for row in rows)
    for row in rows:
        row["share_pct"] = 0.0 if total_abs_balance == 0 else abs(row["balance"]) / total_abs_balance * 100
        row["usage_ratio_pct"] = 0.0 if row["incoming"] == 0 else min(100.0, row["outgoing"] / row["incoming"] * 100)

    return rows


def auxiliary_total(df: pd.DataFrame, include_credit_pending: bool = False) -> float:
    rows = account_balance_rows(df)
    if not include_credit_pending:
        rows = [row for row in rows if row.get("main_net_policy") != MAIN_NET_CREDIT_PENDING]
    return float(sum(row["balance"] for row in rows))


def _safe_money(value) -> float:
    try:
        return round(float(str(value or 0).replace(",", ".")), 2)
    except (TypeError, ValueError):
        return 0.0


def _support_summary_for_account_scope(scope: str, movements: pd.DataFrame) -> dict[str, float | int]:
    try:
        from money_manager.services.account_scope_service import debts_for_scope, receivables_for_scope

        debt_rows = debts_for_scope(scope)
        receivable_rows = receivables_for_scope(scope)
    except Exception:
        debt_rows = []
        receivable_rows = []

    active_debts = [row for row in debt_rows if str(row.get("status") or "active").casefold() == "active" and _safe_money(row.get("remaining_amount")) > 0]
    active_receivables = [row for row in receivable_rows if str(row.get("status") or "active").casefold() == "active" and _safe_money(row.get("remaining_amount")) > 0]
    debts_remaining = round(sum(_safe_money(row.get("remaining_amount")) for row in active_debts), 2)
    receivables_remaining = round(sum(_safe_money(row.get("remaining_amount")) for row in active_receivables), 2)

    if movements is not None and not movements.empty and "type" in movements.columns:
        inv_rows = movements[movements["type"].fillna("").astype(str).str.casefold() == "investment"]
    else:
        inv_rows = pd.DataFrame()
    investment_total = 0.0
    if not inv_rows.empty:
        amount_col = "account_signed_amount" if "account_signed_amount" in inv_rows.columns else "signed_amount" if "signed_amount" in inv_rows.columns else "amount"
        try:
            investment_total = round(float(pd.to_numeric(inv_rows[amount_col], errors="coerce").fillna(0.0).abs().sum()), 2)
        except Exception:
            investment_total = 0.0

    return {
        "debts_total": debts_remaining,
        "debts_count": len(active_debts),
        "receivables_total": receivables_remaining,
        "receivables_count": len(active_receivables),
        "investments_total": investment_total,
        "investments_count": int(len(inv_rows)),
        "net_with_support": 0.0,
    }


def _method_display_name(method: dict) -> str:
    return str(method.get("name") or method.get("label") or method.get("id") or "Payment method")


def _payment_method_views(methods: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for method in methods:
        rules = method.get("rules") if isinstance(method.get("rules"), dict) else {}
        row = dict(method)
        row["label"] = _method_display_name(row)
        row["display_name"] = row["label"]
        row["due_day"] = row.get("due_day") or rules.get("due_day") or ""
        row["statement_day"] = row.get("statement_day") or rules.get("statement_day") or ""
        row["aliases_text"] = ", ".join(row.get("aliases") or [])
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        card_meta = metadata.get("card") if isinstance(metadata.get("card"), dict) else {}
        row["card_network"] = str(card_meta.get("network") or "")
        row["card_last4"] = str(card_meta.get("last4") or "")
        row["card_holder_name"] = str(card_meta.get("holder_name") or "")
        row["card_expiry_month"] = str(card_meta.get("expiry_month") or "")
        row["card_expiry_year"] = str(card_meta.get("expiry_year") or "")
        row["card_expiry"] = "/".join(part for part in [row["card_expiry_month"], row["card_expiry_year"]] if part)
        row["is_credit"] = str(row.get("method_type") or "") == "credit_card" or str(row.get("settlement_mode") or "") == "delayed"
        rows.append(row)
    return rows


def _account_identity_view(account: dict, summary: dict | None = None) -> dict:
    row = dict(account)
    key = str(row.get("key") or row.get("id") or summary.get("account_id") if summary else row.get("key") or row.get("id") or "")
    row["key"] = key
    row["id"] = row.get("id") or key
    row["label"] = str(row.get("label") or row.get("name") or (summary or {}).get("label") or key)
    row["display_label"] = row.get("display_label") or row["label"]
    row["account_kind"] = str(row.get("account_kind") or row.get("type") or "other")
    row["parent_account_id"] = str(row.get("parent_account_id") or row.get("parent_key") or "")
    row["parent_key"] = row["parent_account_id"]
    row["is_active"] = bool(row.get("is_active", True)) and not bool(row.get("is_archived")) and not bool(row.get("is_closed"))
    row["is_archived"] = bool(row.get("is_archived")) or not bool(row.get("is_active", True))
    row["is_technical"] = bool(row.get("is_container")) or bool(row.get("is_liability")) or row["account_kind"] in {"container", "credit_card_liability"}
    if summary:
        row.update({
            "balance": _safe_money(summary.get("net_balance")),
            "net_balance": _safe_money(summary.get("net_balance")),
            "pending_total": _safe_money(summary.get("pending_total")),
            "recurring_monthly_total": _safe_money(summary.get("recurring_monthly_total")),
            "payables_total": _safe_money(summary.get("payables_total")),
            "net_after_pending": _safe_money(summary.get("net_after_pending")),
            "net_after_payables": _safe_money(summary.get("net_after_payables")),
            "projected_net": _safe_money(summary.get("projected_net")),
            "transactions_count": int(summary.get("transactions_count") or 0),
            "payment_methods_count": int(summary.get("payment_methods_count") or 0),
            "dependent_accounts_count": int(summary.get("dependent_accounts_count") or 0),
            "scope_summary": dict(summary),
        })
    else:
        row.setdefault("balance", _account_initial_balance(row))
        row.setdefault("net_balance", row.get("balance", 0.0))
        row.setdefault("pending_total", 0.0)
        row.setdefault("recurring_monthly_total", 0.0)
        row.setdefault("payables_total", 0.0)
        row.setdefault("net_after_pending", row.get("balance", 0.0))
        row.setdefault("net_after_payables", row.get("balance", 0.0))
        row.setdefault("projected_net", row.get("balance", 0.0))
        row.setdefault("transactions_count", 0)
        row.setdefault("payment_methods_count", 0)
        row.setdefault("dependent_accounts_count", 0)
        row.setdefault("scope_summary", {})
    row["balance_tone"] = "positive" if _safe_money(row.get("balance")) >= 0 else "negative"
    return row


def _lightweight_account_summary_by_key(df: pd.DataFrame, accounts_by_key: dict[str, dict] | None = None) -> dict[str, dict]:
    """Cheap balance/count index for rows that do not need pending/projected totals.

    The account landing page only shows a compact balance for dependent/technical
    accounts. Building a full scope summary for each of them repeatedly scans
    transactions, payment methods, recurring rules and payables. This index does
    the transaction pass once and keeps navigation noticeably faster.
    """
    accounts_by_key = accounts_by_key or {
        str(account.get("key") or account.get("id") or ""): dict(account)
        for account in all_accounts(include_archived=True, include_main=True)
    }
    result: dict[str, dict] = {}
    movement_sum: dict[str, float] = {}
    movement_count: dict[str, int] = {}

    try:
        movements = account_movements(df, include_sparagnat_cash=True)
    except Exception:
        movements = pd.DataFrame()
    if not movements.empty and "account_key" in movements.columns:
        grouped = movements.groupby("account_key")["account_signed_amount"].agg(["sum", "count"])
        movement_sum = {str(key): float(row["sum"] or 0.0) for key, row in grouped.iterrows()}
        movement_count = {str(key): int(row["count"] or 0) for key, row in grouped.iterrows()}

    main_total = 0.0
    main_count = 0
    try:
        main_rows = main_account_transactions(df)
        if not main_rows.empty:
            value_col = "account_signed_amount" if "account_signed_amount" in main_rows.columns else "signed_amount"
            main_total = float(pd.to_numeric(main_rows.get(value_col, 0.0), errors="coerce").fillna(0.0).sum())
            main_count = int(len(main_rows))
    except Exception:
        pass

    for key, account in accounts_by_key.items():
        if not key:
            continue
        initial = _account_initial_balance(account)
        if key == MAIN_ACCOUNT_KEY:
            movement_balance = main_total
            count = main_count
        else:
            movement_balance = movement_sum.get(key, 0.0)
            count = movement_count.get(key, 0)
        net = _safe_money(initial + movement_balance)
        result[key] = {
            "account_id": key,
            "net_balance": net,
            "balance": net,
            "pending_total": 0.0,
            "recurring_monthly_total": 0.0,
            "payables_total": 0.0,
            "net_after_pending": net,
            "net_after_payables": net,
            "projected_net": net,
            "transactions_count": count,
            "payment_methods_count": 0,
            "dependent_accounts_count": 0,
        }
    return result


def accounts_page_context(df: pd.DataFrame) -> dict:
    """Build the Conti Correnti-first accounts landing page.

    The old implementation returned one mixed bucket of auxiliary/liquid rows.
    Prompt 16 needs a stronger page model: global totals first, then real
    financial centers, with dependent wallets and payment methods visually under
    their parent account.
    """
    try:
        from money_manager.services.account_scope_service import (
            account_level,
            account_level_label,
            all_financial_center_summaries,
            dependent_accounts_for,
            financial_centers,
            global_balance_summary,
            payment_methods_for_account,
            scope_balance_summary,
        )
    except Exception:
        rows = account_balance_rows(df)
        return {
            "accounts": rows,
            "financial_centers_overview": rows,
            "global_summary": {"net_balance": sum(float(row.get("balance", 0) or 0) for row in rows)},
            "totals": {"balance": sum(float(row.get("balance", 0) or 0) for row in rows), "incoming": 0.0, "outgoing": 0.0, "movements": 0},
            "dependent_groups": [],
            "payment_method_groups": [],
            "archived_accounts": [],
            "technical_accounts": [],
        }

    accounts_by_key = {str(account.get("key") or account.get("id") or ""): dict(account) for account in all_accounts(include_archived=True, include_main=True)}
    center_summary_by_id = {str(row.get("account_id") or row.get("key") or ""): dict(row) for row in all_financial_center_summaries(df=df)}
    global_summary = dict(global_balance_summary(df=df))
    lightweight_summary_by_key = _lightweight_account_summary_by_key(df, accounts_by_key)

    centers: list[dict] = []
    seen_center_ids: set[str] = set()
    for center in financial_centers(include_archived=False):
        center_id = str(center.get("key") or center.get("id") or "")
        if not center_id:
            continue
        seen_center_ids.add(center_id)
        summary = center_summary_by_id.get(center_id) or scope_balance_summary(f"account:{center_id}", df=df)
        row = _account_identity_view(dict(center), summary)
        row["account_level"] = account_level(center)
        row["account_level_label"] = account_level_label(center)
        row["is_cashflow_account"] = row["account_level"] == 2
        dependents = []
        for dep in dependent_accounts_for(center_id, include_archived=False):
            dep_id = str(dep.get("key") or dep.get("id") or "")
            dep_summary = lightweight_summary_by_key.get(dep_id, {}) if dep_id else {}
            dependents.append(_account_identity_view(dict(dep), dep_summary))
        methods = _payment_method_views(payment_methods_for_account(center_id, include_archived=False))
        row["dependent_accounts"] = dependents
        row["dependent_accounts_count"] = len(dependents)
        row["payment_methods"] = methods
        row["payment_methods_count"] = len(methods)
        row["cards_count"] = sum(1 for method in methods if str(method.get("method_type") or "") in {"debit_card", "credit_card", "prepaid_card", "wallet_linked_card"})
        centers.append(row)

    dependent_groups: list[dict] = []
    payment_method_groups: list[dict] = []
    for center in centers:
        if center.get("dependent_accounts"):
            dependent_groups.append({"parent": center, "accounts": center.get("dependent_accounts", [])})
        if center.get("payment_methods"):
            payment_method_groups.append({"parent": center, "methods": center.get("payment_methods", [])})

    archived_accounts: list[dict] = []
    technical_accounts: list[dict] = []
    for key, account in accounts_by_key.items():
        if not key or key in seen_center_ids:
            continue
        summary = lightweight_summary_by_key.get(key)
        row = _account_identity_view(account, summary)
        is_default_credit_bucket = key == "credit_card" and row.get("account_kind") == "credit_card_liability" and not row.get("is_custom")
        if is_default_credit_bucket:
            # The default credit-card liability bucket is an implementation detail.
            # Users add real credit cards as payment methods inside a Conto; do not
            # make this bucket look like a separate account on All Conti.
            continue
        if row.get("is_archived") or row.get("is_closed"):
            archived_accounts.append(row)
        elif row.get("is_technical"):
            technical_accounts.append(row)

    total_in = sum(float(row.get("incoming", 0.0) or 0.0) for row in centers)
    total_out = sum(float(row.get("outgoing", 0.0) or 0.0) for row in centers)
    current_accounts = [row for row in centers if int(row.get("account_level") or 0) == 1]
    cashflow_accounts = [row for row in centers if int(row.get("account_level") or 0) == 2]
    all_dependents = []
    for group in dependent_groups:
        parent = group.get("parent") or {}
        for child in group.get("accounts", []):
            child = dict(child)
            child["parent_label"] = parent.get("label", "")
            child["parent_key"] = parent.get("key", "")
            all_dependents.append(child)

    return {
        "accounts": centers,
        "financial_centers_overview": centers,
        "current_accounts_overview": current_accounts,
        "cashflow_overview": cashflow_accounts,
        "dependent_accounts_overview": all_dependents,
        "global_summary": global_summary,
        "dependent_groups": dependent_groups,
        "payment_method_groups": payment_method_groups,
        "archived_accounts": archived_accounts,
        "technical_accounts": technical_accounts,
        "totals": {
            "balance": _safe_money(global_summary.get("net_balance")),
            "incoming": float(total_in),
            "outgoing": float(total_out),
            "movements": int(global_summary.get("transactions_count") or sum(int(row.get("transactions_count") or 0) for row in centers)),
            "current_accounts_count": len(current_accounts),
            "cashflow_count": len(cashflow_accounts),
            "dependent_accounts_count": len(all_dependents),
            "payment_methods_count": sum(int(row.get("payment_methods_count") or 0) for row in centers),
        },
    }


def _parent_account_options_for_linking(exclude_key: str = "") -> list[dict]:
    """Accounts that can own/link dependent wallets.

    Prompt 11G moved bank ownership to current accounts, so dependent wallets
    should be linkable to a current account as well as to legacy container
    buckets. Credit liabilities are excluded because they are not funding parents.
    """
    options: list[dict] = []
    for account in all_accounts(include_archived=False, include_main=True):
        key = str(account.get("key") or account.get("id") or "")
        if not key or key == exclude_key:
            continue
        kind = str(account.get("account_kind") or account.get("type") or "")
        if kind == "credit_card_liability" or account.get("is_liability"):
            continue
        if not (account.get("is_current_account") or account.get("is_container") or kind in {"current_account", "container"}):
            continue
        options.append({
            "key": key,
            "value": key,
            "label": str(account.get("label") or account.get("name") or key),
            "account_kind": kind,
            "is_current_account": bool(account.get("is_current_account") or kind == "current_account"),
            "is_container": bool(account.get("is_container") or kind == "container"),
        })
    return sorted(options, key=lambda item: (0 if item.get("is_current_account") else 1, str(item.get("label") or "")))

def account_detail_context(df: pd.DataFrame, account_key: str) -> dict | None:
    account_key = normalize_account_key(account_key)
    account = account_by_key(account_key, include_archived=True)
    if not account:
        return None

    try:
        from money_manager.services.account_scope_service import (
            cards_for_account,
            dependent_accounts_for,
            payment_methods_for_account,
            scope_balance_summary,
            transactions_for_scope,
        )

        scoped_summary = scope_balance_summary(f"account:{account_key}", df=df)
        movements = transactions_for_scope(df, f"account:{account_key}")
        scoped_cards = cards_for_account(account_key, include_archived=True)
        scoped_methods = payment_methods_for_account(account_key, include_archived=False)
        dependent_rows_raw = dependent_accounts_for(account_key, include_archived=True)
    except Exception:
        scoped_summary = {}
        movements = account_movements(df, account_key=account_key) if account_key != MAIN_ACCOUNT_KEY else main_account_transactions(df)
        scoped_cards = account.get("cards", [])
        scoped_methods = []
        dependent_rows_raw = []

    if account_key == PAYPAL_ACCOUNT_KEY:
        linked_paypal = _paypal_credit_linked_paypal_movements(df)
        if not linked_paypal.empty:
            movements = pd.concat([movements, linked_paypal], ignore_index=True, sort=False) if not movements.empty else linked_paypal
            if "date" in movements.columns:
                movements["date"] = pd.to_datetime(movements["date"], errors="coerce")
                movements = movements.sort_values(by=["date"], ascending=False)

    if movements.empty and account_key != MAIN_ACCOUNT_KEY:
        movements = account_movements(df, account_key=account_key)
    if "account_signed_amount" not in movements.columns and "signed_amount" in movements.columns:
        movements = movements.copy()
        movements["account_signed_amount"] = movements["signed_amount"]
    incoming = _sum_direction(movements, "in") if "account_signed_amount" in movements.columns else 0.0
    outgoing = _sum_direction(movements, "out") if "account_signed_amount" in movements.columns else 0.0
    balance = float(scoped_summary.get("net_balance", _account_initial_balance(account)) or 0.0)

    dependent_rows: list[dict] = []
    for dep in dependent_rows_raw:
        dep_key = str(dep.get("key") or dep.get("id") or "")
        dep_summary = {}
        if dep_key:
            try:
                from money_manager.services.account_scope_service import scope_balance_summary

                dep_summary = scope_balance_summary(f"account:{dep_key}", df=df)
            except Exception:
                dep_summary = {}
        dependent_rows.append(_account_identity_view(dict(dep), dep_summary))

    method_views = _payment_method_views(scoped_methods)
    card_method_types = {"debit_card", "credit_card", "prepaid_card", "wallet_linked_card"}
    card_method_views = [method for method in method_views if str(method.get("method_type") or "") in card_method_types]
    other_method_views = [method for method in method_views if str(method.get("method_type") or "") not in card_method_types]
    card_views = _payment_method_views(scoped_cards) if scoped_cards and isinstance(scoped_cards[0], dict) else scoped_cards

    summary = dict(account)
    parent_id = str(account.get("parent_account_id") or account.get("parent_key") or "")
    summary.update({
        "key": account_key,
        "id": account.get("id") or account_key,
        "label": account_label_for_key(account_key),
        "display_label": account.get("label") or account_label_for_key(account_key),
        "description": account_description_for_key(account_key),
        "initial_balance": _account_initial_balance(account),
        "movement_balance": balance - _account_initial_balance(account),
        "balance": balance,
        "net_balance": balance,
        "income": incoming,
        "incoming": incoming,
        "expenses": outgoing,
        "outgoing": outgoing,
        "count": int(len(movements)),
        "balance_tone": "positive" if balance >= 0 else "negative",
        "cards": card_views,
        "payment_methods": method_views,
        "card_payment_methods": card_method_views,
        "other_payment_methods": other_method_views,
        "payment_methods_count": len(method_views),
        "card_payment_methods_count": len(card_method_views),
        "dependent_accounts": dependent_rows,
        "dependent_accounts_count": len(dependent_rows),
        "parent_account_id": parent_id,
        "parent_label": account_label_for_key(parent_id) if parent_id else "",
        "scope_summary": scoped_summary,
        "is_archived": bool(account.get("is_archived")) or not bool(account.get("is_active", True)),
        "is_closed": bool(account.get("is_closed")),
        "is_default": bool(account.get("is_default")),
    })
    local_summary = {
        "net_balance": balance,
        "pending_total": _safe_money(scoped_summary.get("pending_total")),
        "recurring_monthly_total": _safe_money(scoped_summary.get("recurring_monthly_total")),
        "payables_total": _safe_money(scoped_summary.get("payables_total")),
        "net_after_pending": _safe_money(scoped_summary.get("net_after_pending", balance)),
        "net_after_payables": _safe_money(scoped_summary.get("net_after_payables", balance)),
        "projected_net": _safe_money(scoped_summary.get("projected_net", balance)),
        "transactions_count": int(scoped_summary.get("transactions_count") or int(len(movements))),
    }
    local_summary.update(_support_summary_for_account_scope(f"account:{account_key}", movements))
    local_summary["net_with_support"] = round(
        local_summary["projected_net"]
        - local_summary["debts_total"]
        + local_summary["receivables_total"],
        2,
    )

    # The current template shows the recent movement list; keep expensive all-row
    # formatting and full-history category/month charts out of the initial GET.
    recent_movements = movements.head(10).copy() if not movements.empty else movements
    monthly = _monthly_summary_for_account(movements, limit=6)
    max_month = max([row["total"] for row in monthly], default=0.0)
    for row in monthly:
        row["in_pct"] = 0.0 if max_month == 0 else row["incoming"] / max_month * 100
        row["out_pct"] = 0.0 if max_month == 0 else row["outgoing"] / max_month * 100
        row["net_pct"] = 0.0 if max_month == 0 else abs(row["net"]) / max_month * 100
        row["net_tone"] = "positive" if row["net"] >= 0 else "negative"

    top_categories = _top_categories(recent_movements)
    display = _prepare_account_movements_for_display(recent_movements)

    from datetime import date

    return {
        "today": date.today().isoformat(),
        "account": summary,
        "local_summary": local_summary,
        "dependent_accounts": dependent_rows,
        "payment_methods": method_views,
        "card_payment_methods": card_method_views,
        "other_payment_methods": other_method_views,
        "cards": card_views,
        "movements": display,
        "monthly": monthly,
        "top_categories": top_categories,
        "parent_account_options": _parent_account_options_for_linking(exclude_key=account_key),
        "policy_options": [
            {"value": MAIN_NET_SEPARATE, "label": "Separate when explicit"},
            {"value": MAIN_NET_AFFECTS, "label": "Affects selected/global net"},
            {"value": MAIN_NET_CREDIT_PENDING, "label": "Credit / pending"},
        ],
        "totals": {
            "balance": summary["balance"],
            "incoming": summary["incoming"],
            "outgoing": summary["outgoing"],
            "net_flow": summary["incoming"] - summary["outgoing"],
            "movements": summary["count"],
        },
    }


def _ensure_payment_methods_after_account_change() -> None:
    """Create/repair default payment methods after account settings change."""
    try:
        from money_manager.services.payment_method_service import ensure_payment_methods_file

        ensure_payment_methods_file()
    except Exception:
        pass


def create_custom_account_from_form(form) -> dict | None:
    """Persist a new custom liquid account from the accounts page form."""
    account = create_config_account_from_form(form)
    if account:
        _ensure_payment_methods_after_account_change()
    return account


def update_account_settings_from_form(account_key: str, form) -> dict | None:
    account = update_account_from_form(account_key, form)
    if account:
        _ensure_payment_methods_after_account_change()
    return account


def ensure_prepaid_card_balance_account(parent_account_key: str, card_name: str = "", user_id: str | None = None) -> str:
    """Return/create the dependent stored-balance account used by one prepaid card.

    Prepaid-card expenses should reduce the prepaid balance, not the parent bank
    account again.  Reloads/top-ups are recorded separately as Internal Transfer /
    Money Transfer movements from the bank to this dependent account.
    """
    parent_key = normalize_account_key(parent_account_key, user_id=user_id)
    base_name = str(card_name or "Prepaid card").strip() or "Prepaid card"
    account_key = f"{parent_key}_{slugify(base_name)}_balance"

    existing = account_by_key(account_key, user_id=user_id, include_archived=True)
    if existing:
        return account_key

    create_config_account_from_form({
        "key": account_key,
        "label": f"{base_name} balance",
        "type": "prepaid_balance",
        "currency": "EUR",
        "institution": "",
        "iban": "",
        "bic_swift": "",
        "initial_balance": "0",
        "description": "Stored balance for a prepaid card. Reload it with Internal Transfer / Money Transfer; payments spend this balance only.",
        "aliases": f"{base_name}, {base_name} balance",
        "category_aliases": "",
        "category_match_enabled": "0",
        "parent_account_id": parent_key,
        "main_net_policy": MAIN_NET_SEPARATE,
    }, user_id=user_id)
    return account_key


def archive_account_from_form(account_key: str) -> bool:
    return archive_account(account_key)


def restore_account_from_form(account_key: str) -> bool:
    return restore_account(account_key)


def add_card_from_form(account_key: str, form) -> dict | None:
    return add_card_to_account(account_key, form)


def archive_card_from_form(account_key: str, card_id: str) -> bool:
    return archive_card(account_key, card_id)


def reconcile_account_balance(df: pd.DataFrame, account_key: str, target_balance: float, movement_date: str, description: str = "") -> dict | None:
    """Create an adjustment movement so an auxiliary account matches the real balance.

    Example: if Cash Flow currently says 1000 and you actually have 150, this
    creates an expense of 850 on Cash Flow only. It does not touch the main bank
    net because the account tag routes it to the separate account analysis.
    """
    from datetime import date
    from money_manager.repositories.transactions import append_transaction

    key = normalize_account_key(account_key)
    if key not in auxiliary_account_keys():
        return None

    rows_by_key = {row["key"]: row for row in account_balance_rows(df)}
    summary = rows_by_key.get(key)
    if not summary:
        return None

    current_balance = float(summary["balance"])
    target_balance = float(target_balance)
    delta = target_balance - current_balance
    if abs(delta) < 0.01:
        return {"created": False, "delta": 0.0, "current_balance": current_balance, "target_balance": target_balance}

    tx_type = "income" if delta > 0 else "expense"
    amount = abs(delta)
    label = account_label_for_key(key)
    safe_date = movement_date or date.today().isoformat()
    desc = description.strip() or f"Account cleanup: adjusted {label} from € {current_balance:.2f} to € {target_balance:.2f}."

    append_transaction({
        "type": tx_type,
        "date": safe_date,
        "category": "Account cleanup",
        "sub_category": f"Reconcile to € {target_balance:.2f}",
        "amount": amount,
        "account": label,
        "description": desc,
    })

    return {
        "created": True,
        "type": tx_type,
        "amount": amount,
        "delta": delta,
        "current_balance": current_balance,
        "target_balance": target_balance,
    }


def _infer_account_from_row(row) -> AccountInference:
    category_lookup, category_search = _category_alias_lookup()
    return _infer_account_from_row_cached(row, category_lookup, category_search)


def _infer_account_from_row_cached(
    row,
    category_lookup: dict[str, str],
    category_search: list[tuple[str, str]],
) -> AccountInference:
    raw_account = row.get("account", "")
    account_text = _clean_text(raw_account)
    if account_text:
        # PayPal linked-card rows are bank-card payments made through PayPal.
        # Financially they belong to the main bank route; a zero-balance copy is
        # shown on the PayPal account for traceability.
        if account_text in PAYPAL_MAIN_BANK_LINK_ALIASES:
            return AccountInference(MAIN_ACCOUNT_KEY, "paypal_main_bank_link")

        # True legacy PayPal-credit rows still use the credit-card liability route.
        if account_text in PAYPAL_CREDIT_ROUTE_ALIASES:
            return AccountInference(DEFAULT_CREDIT_ACCOUNT_KEY, "paypal_credit_link")
        return AccountInference(normalize_account_key(account_text), "explicit_account")

    # If a cleanup/reconciliation row was saved with a blank account, try to
    # recover the intended liquid account from the text before falling back to
    # the main bank route. Example: description="Cash cleanup" should belong to
    # Cash Flow, not to the main-bank net.
    if _is_cleanup_row(row):
        combined_text = _clean_text(" ".join(str(row.get(field, "") or "") for field in ("category", "sub_category", "description")))
        for key, alias in category_search:
            if alias and alias in combined_text:
                return AccountInference(key, "cleanup_hint")

    category_value = _clean_text(row.get("category", ""))
    if category_value and category_value in category_lookup:
        return AccountInference(category_lookup[category_value], "category_match")

    return AccountInference(MAIN_ACCOUNT_KEY, "main_route")


def _account_signed_amount(row) -> float:
    return _account_signed_amount_cached(row, _account_policy_lookup())


def _account_signed_amount_cached(row, policies: dict[str, str]) -> float:
    amount = float(row.get("amount", 0.0) or 0.0)
    transaction_type = str(row.get("type", ""))
    account_key = row.get("account_key", MAIN_ACCOUNT_KEY)
    route_source = str(row.get("account_route_source", ""))
    category = _clean_text(row.get("category", ""))

    if account_key == MAIN_ACCOUNT_KEY:
        return float(row.get("signed_amount", 0.0) or 0.0)

    if policies.get(str(account_key), account_policy_for_key(account_key)) == MAIN_NET_CREDIT_PENDING and transaction_type == "expense":
        # Credit-card charges increase the outstanding balance (negative from the
        # account point of view). The later statement payment reduces that
        # outstanding balance, so it is positive here. Legacy PayPal-credit
        # payment rows are already the main-bank payment itself, so they are
        # displayed as linked card usage but do not alter the card outstanding
        # balance a second time.
        if route_source == "paypal_credit_link" and _is_credit_settlement_row(row):
            return 0.0
        return amount if _is_credit_settlement_row(row) else -amount

    # A blank-account expense categorized as a matching account alias is usually
    # a top-up: money leaves the main bank but becomes available on that liquid
    # account. Cleanup/reconciliation rows are different: they are corrections to
    # the liquid account balance only, so an expense must reduce the liquid account.
    if transaction_type == "expense" and route_source == "category_match" and not _is_cleanup_row(row):
        return amount

    if transaction_type == "income":
        return amount
    if transaction_type == "expense":
        return -amount
    if transaction_type == "investment":
        return amount if category == "dividend" else -amount
    return float(row.get("signed_amount", 0.0) or 0.0)





def _credit_settlement_like_mask(df: pd.DataFrame) -> pd.Series:
    if df.empty:
        return pd.Series(dtype=bool, index=df.index)
    description = df.get("description", pd.Series("", index=df.index)).fillna("").astype(str).map(_clean_text)
    sub_category = df.get("sub_category", pd.Series("", index=df.index)).fillna("").astype(str).map(_clean_text)
    account = df.get("account", pd.Series("", index=df.index)).fillna("").astype(str).map(_clean_text)
    combined = description + " " + sub_category
    explicit_statement_payment = (
        combined.str.contains("statement payment", na=False)
        | combined.str.contains("credit card payment", na=False)
        | combined.str.contains("credit statement payment", na=False)
        | combined.str.contains("settlement", na=False)
    )
    legacy_paypal_payment = account.isin(PAYPAL_CREDIT_ROUTE_ALIASES) & combined.str.contains("payment", na=False)
    return explicit_statement_payment | legacy_paypal_payment


def _is_credit_settlement_row(row) -> bool:
    description = _clean_text(row.get("description", ""))
    sub_category = _clean_text(row.get("sub_category", ""))
    account = _clean_text(row.get("account", ""))
    text = f"{description} {sub_category}"
    explicit_statement_payment = (
        "statement payment" in text
        or "credit card payment" in text
        or "credit statement payment" in text
        or "settlement" in text
    )
    legacy_paypal_payment = account in PAYPAL_CREDIT_ROUTE_ALIASES and "payment" in text
    return explicit_statement_payment or legacy_paypal_payment

def _is_cleanup_row(row) -> bool:
    text = _clean_text(" ".join(str(row.get(field, "") or "") for field in ("category", "sub_category", "description")))
    return _looks_like_cleanup_text(text)


def _cleanup_like_mask(df: pd.DataFrame) -> pd.Series:
    if df.empty:
        return pd.Series(dtype=bool, index=df.index)

    category = df.get("category", pd.Series("", index=df.index)).fillna("").astype(str)
    sub_category = df.get("sub_category", pd.Series("", index=df.index)).fillna("").astype(str)
    description = df.get("description", pd.Series("", index=df.index)).fillna("").astype(str)
    combined = (category + " " + sub_category + " " + description).map(_clean_text)
    return combined.map(_looks_like_cleanup_text)


def _looks_like_cleanup_text(text: str) -> bool:
    value = _clean_text(text)
    if not value:
        return False
    cleanup_markers = (
        "account cleanup",
        "clean up",
        "cleanup",
        "reconcile",
        "reconciliation",
        "manual reconciliation",
        "manual adjustment",
        "balance adjustment",
        "balance correction",
        "balance cleanup",
        "adjusted",
        "correction",
        "rettifica",
        "riconcil",
        "saldo reale",
    )
    return any(marker in value for marker in cleanup_markers)

def _source_label_for_transaction(row) -> str:
    transaction_type = str(row.get("type", "")).strip().title()
    route_source = str(row.get("account_route_source", ""))
    if route_source == "paypal_main_bank_link":
        return "PayPal via main bank card"
    if account_policy_for_key(row.get("account_key")) == MAIN_NET_CREDIT_PENDING:
        if route_source == "paypal_credit_link":
            return "PayPal via credit card"
        if _is_credit_settlement_row(row):
            return "Credit-card statement payment"
    if transaction_type == "Expense" and route_source == "category_match":
        if account_policy_for_key(row.get("account_key")) == MAIN_NET_CREDIT_PENDING:
            return "Credit-card charge"
        return "Transfer in"
    if transaction_type == "Investment":
        return "Investment movement"
    if route_source == "cleanup_hint":
        return "Cleanup / reconciliation"
    if route_source == "explicit_account":
        return f"{transaction_type} from account" if transaction_type else "Explicit account"
    return transaction_type or "Movement"


def _account_initial_balance(account: dict) -> float:
    try:
        return float(account.get("initial_balance", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _paypal_credit_linked_paypal_movements(df: pd.DataFrame) -> pd.DataFrame:
    """Return zero-balance PayPal view rows for linked-card PayPal payments.

    PayPal can be only the checkout channel while the real funding route is the
    main bank card or a credit-card liability.  These copies keep PayPal visible
    as a separate account without double-counting the PayPal wallet balance.
    """
    if df.empty or "account" not in df.columns:
        return _empty_account_movements()

    account_values = df["account"].fillna("").astype(str).map(_clean_text)
    linked_mask = account_values.isin(PAYPAL_CREDIT_ROUTE_ALIASES | PAYPAL_MAIN_BANK_LINK_ALIASES)
    linked = df[linked_mask].copy()
    if linked.empty:
        return _empty_account_movements()

    linked["account_key"] = PAYPAL_ACCOUNT_KEY
    linked["account_label"] = account_label_for_key(PAYPAL_ACCOUNT_KEY)
    linked["account_route_source"] = "paypal_linked_view"
    linked["account_signed_amount"] = 0.0
    linked["display_signed_amount"] = -pd.to_numeric(linked.get("amount", 0.0), errors="coerce").fillna(0.0).abs()
    linked["source"] = "linked_transaction"
    linked["source_label"] = account_values.loc[linked.index].map(
        lambda value: "PayPal via main bank card" if value in PAYPAL_MAIN_BANK_LINK_ALIASES else "PayPal via credit card"
    )
    linked["source_url_kind"] = "transaction"
    linked["source_row_index"] = linked.index
    linked["direction"] = "linked"
    linked["is_auxiliary_account"] = True
    return linked


def _sparagnat_cash_movements() -> pd.DataFrame:
    try:
        from money_manager.services.sparagnat_service import KIND_CASH_COLLECTED
        from money_manager.repositories.sparagnat import load_entries
    except Exception:
        return _empty_account_movements()

    try:
        rows = load_entries()
    except Exception:
        return _empty_account_movements()
    if not rows:
        return _empty_account_movements()

    df = pd.DataFrame(rows)
    if df.empty or "kind" not in df.columns:
        return _empty_account_movements()

    df = df[df["kind"] == KIND_CASH_COLLECTED].copy()
    if df.empty:
        return _empty_account_movements()

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    df["type"] = "income"
    df["category"] = "Sparagnat e Fottut"
    df["sub_category"] = "Cash collected"
    df["account"] = "cash"
    df["account_key"] = "cash_flow"
    df["account_label"] = account_label_for_key("cash_flow")
    df["account_route_source"] = "sparagnat_cash_collected"
    df["signed_amount"] = df["amount"]
    df["account_signed_amount"] = df["amount"]
    df["source"] = "sparagnat"
    df["source_label"] = "Cash collected"
    df["source_url_kind"] = "sparagnat"
    df["source_row_index"] = ""
    df["direction"] = "in"
    df["is_auxiliary_account"] = True
    return df


def _monthly_summary_for_account(df: pd.DataFrame, limit: int | None = 4) -> list[dict]:
    if df.empty:
        return []

    tmp = df.dropna(subset=["date"]).copy()
    if tmp.empty:
        return []

    tmp["month"] = tmp["date"].dt.to_period("M").astype(str)
    tmp["incoming_value"] = tmp["account_signed_amount"].clip(lower=0)
    tmp["outgoing_value"] = (-tmp["account_signed_amount"].clip(upper=0))
    grouped = (
        tmp.groupby("month")[["incoming_value", "outgoing_value", "account_signed_amount"]]
        .sum()
        .reset_index()
        .sort_values("month", ascending=False)
    )
    if limit is not None:
        grouped = grouped.head(limit)

    rows = []
    for row in grouped.to_dict(orient="records"):
        incoming = float(row.get("incoming_value", 0.0))
        outgoing = float(row.get("outgoing_value", 0.0))
        net = float(row.get("account_signed_amount", 0.0))
        rows.append({
            "month": row.get("month", ""),
            "incoming": incoming,
            "outgoing": outgoing,
            "net": net,
            "total": incoming + outgoing,
        })
    return rows


def _top_categories(df: pd.DataFrame, limit: int = 6) -> list[dict]:
    if df.empty:
        return []
    tmp = df.copy()
    tmp["category"] = tmp["category"].fillna("Other").replace("", "Other")
    tmp["absolute"] = tmp["account_signed_amount"].abs()
    grouped = tmp.groupby("category", as_index=False)["absolute"].sum().sort_values("absolute", ascending=False).head(limit)
    total = float(grouped["absolute"].max()) if not grouped.empty else 0.0
    rows = []
    for row in grouped.to_dict(orient="records"):
        value = float(row.get("absolute", 0.0))
        rows.append({
            "category": row.get("category", "Other"),
            "total": value,
            "pct": 0.0 if total == 0 else value / total * 100,
        })
    return rows


def _prepare_account_movements_for_display(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []
    display = df.copy()
    for column, default in {
        "source_label": "Movement",
        "direction": "",
        "category": "",
        "description": "",
    }.items():
        if column not in display.columns:
            display[column] = default
    if "account_signed_amount" not in display.columns:
        display["account_signed_amount"] = display.get("signed_amount", 0.0)
    display["date_str"] = display["date"].dt.strftime("%Y-%m-%d")
    if "display_signed_amount" in display.columns:
        display["display_signed_amount"] = pd.to_numeric(display["display_signed_amount"], errors="coerce").fillna(display["account_signed_amount"])
    else:
        display["display_signed_amount"] = display["account_signed_amount"]
    display["amount_abs"] = display["display_signed_amount"].abs()
    display["amount_str"] = display["amount_abs"].map(lambda value: f"{value:.2f}")
    display["signed_amount_str"] = display["display_signed_amount"].map(lambda value: f"{value:+.2f}")
    display["category"] = display["category"].fillna("")
    display["description"] = display["description"].fillna("")
    display["source_label"] = display["source_label"].fillna("Movement")
    display["direction"] = display["display_signed_amount"].map(lambda value: "in" if value >= 0 else "out")
    return display.to_dict(orient="records")


def _sum_direction(df: pd.DataFrame, direction: str) -> float:
    if df.empty:
        return 0.0
    if direction == "in":
        return float(df["account_signed_amount"].clip(lower=0).sum())
    return float((-df["account_signed_amount"].clip(upper=0)).sum())


def _sum_type(df: pd.DataFrame, transaction_type: str) -> float:
    if df.empty or "type" not in df.columns:
        return 0.0
    return float(df.loc[df["type"] == transaction_type, "account_signed_amount"].abs().sum())


def _clean_text(value) -> str:
    text = str(value or "").strip().casefold()
    if text in {"nan", "none"}:
        return ""
    return text


def _empty_account_movements() -> pd.DataFrame:
    return pd.DataFrame(columns=[
        "id",
        "date",
        "category",
        "sub_category",
        "amount",
        "account",
        "description",
        "created_at",
        "type",
        "signed_amount",
        "account_key",
        "account_label",
        "account_route_source",
        "account_signed_amount",
        "source",
        "source_label",
        "source_url_kind",
        "source_row_index",
        "direction",
        "is_auxiliary_account",
        "affects_main_net",
    ])
