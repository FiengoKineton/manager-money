from __future__ import annotations

from typing import Any, Iterable, Mapping
from urllib.parse import urlencode

from flask import url_for

from money_manager.config import DOCUMENT_FOLDERS
from money_manager.config.user_paths import get_current_user_id
from money_manager.security.key_manager import is_encryption_enabled
from money_manager.security.session_vault import is_unlocked
from money_manager.services.preferences_service import load_preferences
from money_manager.utils.privacy import should_mask_sensitive


def _text(value: Any) -> str:
    text = str(value or "").strip()
    if text.casefold() in {"nan", "none", "null"}:
        return ""
    return text


def _needle(value: str | None) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _haystack(*values: Any) -> str:
    chunks: list[str] = []
    for value in values:
        if isinstance(value, (list, tuple, set)):
            chunks.extend(_text(item) for item in value)
        elif isinstance(value, Mapping):
            chunks.extend(_text(v) for v in value.values())
        else:
            chunks.append(_text(value))
    return _needle(" ".join(chunks))


def _matches(query: str, *values: Any) -> bool:
    if not query:
        return False
    hay = _haystack(*values)
    return all(part in hay for part in query.split())


def _limit(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    return items[: max(0, int(limit or 0))]


def _scope_args(account_id: str | None = None, q: str | None = None) -> dict[str, str]:
    args: dict[str, str] = {}
    if q:
        args["q"] = q
    if account_id:
        args["account_id"] = account_id
    return args


def _url(endpoint: str, **kwargs: Any) -> str:
    query = kwargs.pop("query", None)
    base = url_for(endpoint, **{key: value for key, value in kwargs.items() if value not in {None, ""}})
    if query:
        return f"{base}?{urlencode(query)}"
    return base


def search_everything(query: str | None, *, limit_per_group: int = 12) -> dict[str, Any]:
    q = _needle(query)
    user_id = get_current_user_id()
    locked = bool(user_id and is_encryption_enabled(user_id) and not is_unlocked(user_id))
    try:
        preferences = load_preferences()
    except Exception:
        preferences = {}
    mask_sensitive = should_mask_sensitive(preferences)
    include_archived = bool(preferences.get("show_archived_in_search", False))

    groups = [
        {"key": "accounts", "label": "Accounts", "items": []},
        {"key": "methods", "label": "Cards / Payment methods", "items": []},
        {"key": "transactions", "label": "Transactions", "items": []},
        {"key": "pending", "label": "Pending", "items": []},
        {"key": "recurring", "label": "Recurring", "items": []},
        {"key": "payables", "label": "Payables", "items": []},
        {"key": "contacts", "label": "Contacts", "items": []},
        {"key": "documents", "label": "Documents", "items": []},
    ]
    by_key = {group["key"]: group for group in groups}
    if not q:
        return {"q": "", "groups": groups, "locked": locked, "mask_sensitive": mask_sensitive}

    try:
        from money_manager.services.account_config_service import all_accounts, account_label_for_key

        for account in all_accounts(include_archived=True, include_main=True):
            if not include_archived and (account.get("is_archived") or account.get("is_closed") or not account.get("is_active", True)):
                continue
            key = _text(account.get("key") or account.get("id"))
            if _matches(q, key, account.get("label"), account.get("name"), account.get("institution"), account.get("iban"), account.get("bic_swift"), account.get("aliases"), account.get("account_kind")):
                by_key["accounts"]["items"].append({
                    "title": account.get("label") or account.get("name") or key,
                    "meta": account.get("account_kind") or account.get("type") or "account",
                    "snippet": "Archived" if account.get("is_archived") or account.get("is_closed") else account.get("institution") or account.get("description") or "",
                    "url": _url("accounts.account_detail", account_key=key),
                    "account_id": key,
                })
    except Exception:
        pass

    try:
        from money_manager.services.payment_method_service import all_payment_methods

        for method in all_payment_methods(include_archived=True):
            if not include_archived and (method.get("is_archived") or not method.get("is_active", True)):
                continue
            account_id = _text(method.get("linked_account_id") or method.get("funding_account_id") or method.get("settlement_account_id") or method.get("liability_account_id"))
            method_id = _text(method.get("id"))
            if _matches(q, method_id, method.get("name"), method.get("method_type"), method.get("settlement_mode"), method.get("aliases"), account_id):
                endpoint = "accounts.account_payment_method_detail" if account_id else "accounts.accounts_page"
                by_key["methods"]["items"].append({
                    "title": method.get("name") or method_id,
                    "meta": f"{method.get('method_type') or 'method'} · {method.get('settlement_mode') or ''}",
                    "snippet": f"Linked account: {account_id}" if account_id else "Payment method",
                    "url": _url(endpoint, account_key=account_id, method_id=method_id) if account_id else _url("accounts.accounts_page", query={"q": q}),
                    "account_id": account_id,
                })
    except Exception:
        pass

    try:
        from money_manager.services.transaction_service import load_transactions

        df = load_transactions()
        if df is not None and not df.empty:
            data = df.copy().fillna("")
            for idx, row in data.head(2000).iterrows():
                row_dict = row.to_dict()
                account_id = _text(row_dict.get("account_id") or row_dict.get("account_key") or "")
                if _matches(q, row_dict.get("category"), row_dict.get("sub_category"), row_dict.get("description"), row_dict.get("account"), row_dict.get("payment_method_id"), row_dict.get("amount"), row_dict.get("date")):
                    by_key["transactions"]["items"].append({
                        "title": row_dict.get("description") or row_dict.get("category") or f"Transaction {idx}",
                        "meta": f"{row_dict.get('date', '')} · {row_dict.get('type', 'transaction')} · € {row_dict.get('amount', '')}",
                        "snippet": row_dict.get("account") or row_dict.get("sub_category") or "",
                        "url": _url("transactions.transactions_page", query=_scope_args(account_id, q)),
                        "account_id": account_id,
                    })
    except Exception:
        pass

    try:
        from money_manager.repositories.pending import load_pending

        for row in load_pending():
            account_id = _text(row.get("account_id") or row.get("account_key") or "")
            if _matches(q, row.get("category"), row.get("description"), row.get("account"), row.get("pending_kind"), row.get("amount"), row.get("date_due")):
                by_key["pending"]["items"].append({
                    "title": row.get("description") or row.get("category") or f"Pending {row.get('id', '')}",
                    "meta": f"Due {row.get('date_due', '')} · € {row.get('amount', '')}",
                    "snippet": row.get("status") or "pending",
                    "url": _url("pending.pending_page", query=_scope_args(account_id)),
                    "account_id": account_id,
                })
    except Exception:
        pass

    try:
        from money_manager.repositories.recurring import load_recurring

        for row in load_recurring():
            account_id = _text(row.get("account_id") or row.get("account") or "")
            if _matches(q, row.get("name"), row.get("category"), row.get("account"), row.get("amount"), row.get("frequency")):
                by_key["recurring"]["items"].append({
                    "title": row.get("name") or row.get("category") or f"Recurring {row.get('id', '')}",
                    "meta": f"Every {row.get('frequency', '')} month(s) · € {row.get('amount', '')}",
                    "snippet": row.get("category") or "recurring rule",
                    "url": _url("pending.recurring_page", query=_scope_args(account_id)),
                    "account_id": account_id,
                })
    except Exception:
        pass

    try:
        from money_manager.repositories.payables import load_payables

        for row in load_payables():
            account_id = _text(row.get("account_id") or row.get("account") or "")
            if _matches(q, row.get("name"), row.get("payee"), row.get("category"), row.get("description"), row.get("remaining_amount"), row.get("due_date")):
                by_key["payables"]["items"].append({
                    "title": row.get("name") or row.get("payee") or f"Payable {row.get('id', '')}",
                    "meta": f"{row.get('payee', '')} · remaining € {row.get('remaining_amount', '')}",
                    "snippet": row.get("description") or row.get("status") or "payable",
                    "url": _url("payables.payables_page", query=_scope_args(account_id)),
                    "account_id": account_id,
                })
    except Exception:
        pass

    try:
        from money_manager.services.contact_service import search_contacts

        for contact in search_contacts(q, include_archived=include_archived):
            by_key["contacts"]["items"].append({
                "title": contact.get("display_name") or contact.get("company_name") or contact.get("first_name") or "Contact",
                "meta": contact.get("type") or "contact",
                "snippet": "Bank details hidden" if mask_sensitive and (contact.get("iban") or contact.get("bic_swift")) else contact.get("relationship") or contact.get("bank_name") or "",
                "url": _url("contacts.contact_detail", contact_id=contact.get("id")),
            })
    except Exception:
        pass

    if not locked:
        try:
            from money_manager.repositories.documents import list_files

            for folder in DOCUMENT_FOLDERS:
                for filename in list_files(folder):
                    if _matches(q, folder, filename):
                        by_key["documents"]["items"].append({
                            "title": filename,
                            "meta": folder,
                            "snippet": "Document metadata only",
                            "url": _url("documents.documents", query={"folder": folder}),
                        })
        except Exception:
            pass

    for group in groups:
        group["items"] = _limit(group["items"], limit_per_group)
    return {"q": query or "", "groups": groups, "locked": locked, "mask_sensitive": mask_sensitive}
