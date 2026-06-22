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
    create_account_from_form as create_config_account_from_form,
    restore_account,
    update_account_from_form,
)


# Category/account aliases are loaded dynamically from the built-in accounts and the current user accounts.json.



@dataclass(frozen=True)
class AccountInference:
    key: str
    source: str


DEFAULT_CREDIT_ACCOUNT_KEY = "credit_card"


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
    inferences = df.apply(_infer_account_from_row, axis=1)
    df["account_key"] = [inference.key for inference in inferences]
    df["account_route_source"] = [inference.source for inference in inferences]
    df["account_label"] = df["account_key"].map(account_label_for_key)
    df["is_auxiliary_account"] = df["account_key"].isin(auxiliary_account_keys())
    df["affects_main_net"] = _affects_main_net_mask(df)
    df["account_signed_amount"] = df.apply(_account_signed_amount, axis=1)
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

    policies = account_key.map(account_policy_for_key)
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
            "type": option.get("type", "wallet"),
            "currency": option.get("currency", "EUR"),
            "institution": option.get("institution", ""),
            "iban": option.get("iban", ""),
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


def accounts_page_context(df: pd.DataFrame) -> dict:
    rows = account_balance_rows(df)

    # Show Other account as a parent bucket with custom/small accounts below it.
    children_by_parent: dict[str, list[dict]] = {}
    for row in rows:
        parent_key = row.get("parent_key")
        if parent_key:
            children_by_parent.setdefault(parent_key, []).append(row)

    display_rows: list[dict] = []
    for row in rows:
        if row.get("parent_key"):
            continue
        row = dict(row)
        children = children_by_parent.get(row["key"], [])
        row["children"] = children
        if children:
            child_balance = sum(float(child.get("balance", 0.0) or 0.0) for child in children)
            child_incoming = sum(float(child.get("incoming", 0.0) or 0.0) for child in children)
            child_outgoing = sum(float(child.get("outgoing", 0.0) or 0.0) for child in children)
            child_count = sum(int(child.get("count", 0) or 0) for child in children)
            row["own_balance"] = row["balance"]
            row["own_incoming"] = row["incoming"]
            row["own_outgoing"] = row["outgoing"]
            row["own_count"] = row["count"]
            row["balance"] = row["balance"] + child_balance
            row["incoming"] = row["incoming"] + child_incoming
            row["outgoing"] = row["outgoing"] + child_outgoing
            row["count"] = row["count"] + child_count
            row["child_count"] = len(children)
            row["child_balance"] = child_balance
            row["child_incoming"] = child_incoming
            row["child_outgoing"] = child_outgoing
            row["balance_tone"] = "positive" if row["balance"] >= 0 else "negative"
        else:
            row["own_balance"] = row["balance"]
            row["own_incoming"] = row["incoming"]
            row["own_outgoing"] = row["outgoing"]
            row["own_count"] = row["count"]
            row["child_count"] = 0
            row["child_balance"] = 0.0
            row["child_incoming"] = 0.0
            row["child_outgoing"] = 0.0
            row["children"] = []
        display_rows.append(row)

    total_balance = sum(row["balance"] for row in display_rows)
    total_in = sum(row["incoming"] for row in display_rows)
    total_out = sum(row["outgoing"] for row in display_rows)
    return {
        "accounts": display_rows,
        "totals": {
            "balance": float(total_balance),
            "incoming": float(total_in),
            "outgoing": float(total_out),
            "movements": int(sum(row["count"] for row in display_rows)),
        },
    }


def account_detail_context(df: pd.DataFrame, account_key: str) -> dict | None:
    account_key = normalize_account_key(account_key)
    if account_key not in auxiliary_account_keys():
        return None

    rows_by_key = {row["key"]: row for row in account_balance_rows(df)}
    summary = rows_by_key.get(account_key)
    if not summary:
        return None

    movements = account_movements(df, account_key=account_key)
    monthly = _monthly_summary_for_account(movements, limit=None)
    max_month = max([row["total"] for row in monthly], default=0.0)
    for row in monthly:
        row["in_pct"] = 0.0 if max_month == 0 else row["incoming"] / max_month * 100
        row["out_pct"] = 0.0 if max_month == 0 else row["outgoing"] / max_month * 100
        row["net_pct"] = 0.0 if max_month == 0 else abs(row["net"]) / max_month * 100
        row["net_tone"] = "positive" if row["net"] >= 0 else "negative"

    top_categories = _top_categories(movements)
    display = _prepare_account_movements_for_display(movements)

    from datetime import date

    return {
        "today": date.today().isoformat(),
        "account": summary,
        "movements": display,
        "monthly": monthly,
        "top_categories": top_categories,
        "parent_account_options": [row for row in account_balance_rows(df) if row.get("is_container") and row.get("key") != account_key],
        "policy_options": [
            {"value": MAIN_NET_SEPARATE, "label": "Separate when explicit"},
            {"value": MAIN_NET_AFFECTS, "label": "Affects main net"},
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


def create_custom_account_from_form(form) -> dict | None:
    """Persist a new custom liquid account from the accounts page form."""
    return create_config_account_from_form(form)


def update_account_settings_from_form(account_key: str, form) -> dict | None:
    return update_account_from_form(account_key, form)


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
    raw_account = row.get("account", "")
    account_text = _clean_text(raw_account)
    if account_text:
        # Legacy PayPal-credit rows are payments/charges made through the credit-card
        # route.  They must reduce/settle the Credit Card account, while a linked
        # copy is still shown on the PayPal page for traceability.
        if account_text in PAYPAL_CREDIT_ALIASES:
            return AccountInference(DEFAULT_CREDIT_ACCOUNT_KEY, "paypal_credit_link")
        return AccountInference(normalize_account_key(account_text), "explicit_account")

    # If a cleanup/reconciliation row was saved with a blank account, try to
    # recover the intended liquid account from the text before falling back to
    # the main bank route. Example: description="Cash cleanup" should belong to
    # Cash Flow, not to the main-bank net.
    if _is_cleanup_row(row):
        combined_text = _clean_text(" ".join(str(row.get(field, "") or "") for field in ("category", "sub_category", "description")))
        for key, aliases in category_aliases_by_key().items():
            for alias in sorted(aliases, key=len, reverse=True):
                if alias and alias in combined_text:
                    return AccountInference(key, "cleanup_hint")

    category_value = _clean_text(row.get("category", ""))
    if category_value:
        for key, aliases in category_aliases_by_key().items():
            if category_value in aliases:
                return AccountInference(key, "category_match")

    return AccountInference(MAIN_ACCOUNT_KEY, "main_route")


def _account_signed_amount(row) -> float:
    amount = float(row.get("amount", 0.0) or 0.0)
    transaction_type = str(row.get("type", ""))
    account_key = row.get("account_key", MAIN_ACCOUNT_KEY)
    route_source = str(row.get("account_route_source", ""))
    category = _clean_text(row.get("category", ""))

    if account_key == MAIN_ACCOUNT_KEY:
        return float(row.get("signed_amount", 0.0) or 0.0)

    if account_policy_for_key(account_key) == MAIN_NET_CREDIT_PENDING and transaction_type == "expense":
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
    legacy_paypal_payment = account.isin(PAYPAL_CREDIT_ALIASES) & combined.str.contains("payment", na=False)
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
    legacy_paypal_payment = account in PAYPAL_CREDIT_ALIASES and "payment" in text
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
    """Return zero-balance PayPal view rows for legacy PayPal-credit payments.

    A row saved with account=paypal_credit is financially routed through the
    Credit Card account.  The user still expects to see that movement on PayPal,
    because PayPal is the merchant/payment channel.  The linked copy is displayed
    on the PayPal account page but does not change the PayPal wallet balance.
    """
    if df.empty or "account" not in df.columns:
        return _empty_account_movements()

    account_values = df["account"].fillna("").astype(str).map(_clean_text)
    linked = df[account_values.isin(PAYPAL_CREDIT_ALIASES)].copy()
    if linked.empty:
        return _empty_account_movements()

    linked["account_key"] = PAYPAL_ACCOUNT_KEY
    linked["account_label"] = account_label_for_key(PAYPAL_ACCOUNT_KEY)
    linked["account_route_source"] = "paypal_credit_linked_view"
    linked["account_signed_amount"] = 0.0
    linked["display_signed_amount"] = -pd.to_numeric(linked.get("amount", 0.0), errors="coerce").fillna(0.0).abs()
    linked["source"] = "linked_transaction"
    linked["source_label"] = "PayPal via credit card"
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

    rows = load_entries()
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
