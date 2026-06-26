from __future__ import annotations

import re
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Mapping, MutableMapping

from money_manager.config.user_paths import get_current_user_id, user_data_path
from money_manager.security.secure_storage import read_json_secure, write_json_secure

DISCOUNT_BALANCES_FILENAME = "discount_balances.json"
SOURCE_KIND_GIFT_CARD = "gift_card"
SOURCE_KIND_BUONO_SCONTO = "buono_sconto"
SOURCE_KINDS = {SOURCE_KIND_GIFT_CARD, SOURCE_KIND_BUONO_SCONTO}
NEW_SOURCE_SENTINEL = "__new__"

KIND_LABELS = {
    SOURCE_KIND_GIFT_CARD: "Gift card",
    SOURCE_KIND_BUONO_SCONTO: "Buono sconto / reimbursement",
}




def source_kind_options() -> list[dict[str, str]]:
    return [
        {"value": SOURCE_KIND_GIFT_CARD, "label": KIND_LABELS[SOURCE_KIND_GIFT_CARD]},
        {"value": SOURCE_KIND_BUONO_SCONTO, "label": KIND_LABELS[SOURCE_KIND_BUONO_SCONTO]},
    ]


def discount_balances_page_context(user_id: str | None = None) -> dict[str, Any]:
    payload = load_discount_balances(user_id=user_id)
    sources = [_source_for_page(row) for row in payload.get("sources", [])]
    active_sources = [row for row in sources if row.get("is_active")]
    archived_sources = [row for row in sources if not row.get("is_active")]
    events = [_event_for_page(row) for row in reversed(payload.get("events", [])[-80:])]

    total_active = round(sum(_money(row.get("balance")) for row in active_sources), 2)
    gift_total = round(sum(_money(row.get("balance")) for row in active_sources if row.get("kind") == SOURCE_KIND_GIFT_CARD), 2)
    buono_total = round(sum(_money(row.get("balance")) for row in active_sources if row.get("kind") == SOURCE_KIND_BUONO_SCONTO), 2)

    active_sources.sort(key=lambda item: (item.get("display_order", 1000), str(item.get("name") or "").lower()))
    archived_sources.sort(key=lambda item: (str(item.get("name") or "").lower(), item.get("id", "")))

    return {
        "sources": active_sources,
        "archived_sources": archived_sources,
        "events": events,
        "source_kind_options": source_kind_options(),
        "totals": {
            "active": total_active,
            "active_display": f"{total_active:.2f}",
            "gift_card": gift_total,
            "gift_card_display": f"{gift_total:.2f}",
            "buono_sconto": buono_total,
            "buono_sconto_display": f"{buono_total:.2f}",
            "count": len(active_sources),
        },
    }


def create_discount_source_from_form(form: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    name = str(form.get("name") or form.get("source_name") or "").strip()
    if not name:
        return {"ok": False, "error": "Insert a name for the gift card / buono sconto."}
    starting_balance = _money(form.get("balance") or form.get("starting_balance"))
    if starting_balance <= 0:
        return {"ok": False, "error": "Insert a starting balance greater than zero."}

    payload = load_discount_balances(user_id=user_id)
    sources = list(payload.get("sources") or [])
    source = _normalize_source({
        "id": _unique_source_id(name),
        "name": name,
        "kind": _normalize_kind(form.get("kind")),
        "balance": starting_balance,
        "initial_balance": starting_balance,
        "aliases": _split_aliases(form.get("aliases")),
        "is_active": True,
        "display_order": 1000 + len(sources),
        "created_at": _now(),
        "updated_at": _now(),
        "archived_at": "",
    }, len(sources))
    sources.append(source)

    events = list(payload.get("events") or [])
    events.append(_balance_event(source, event_type="create", amount=starting_balance, balance_before=0.0, balance_after=starting_balance))
    payload["sources"] = sources
    payload["events"] = events[-1000:]
    save_discount_balances(payload, user_id=user_id)
    return {"ok": True, "message": f"{source['name']} saved.", "source": source}


def update_discount_source_from_form(source_id: str, form: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    source_id = str(source_id or form.get("source_id") or "").strip()
    if not source_id:
        return {"ok": False, "error": "Missing balance id."}

    payload = load_discount_balances(user_id=user_id)
    sources = list(payload.get("sources") or [])
    index = next((idx for idx, row in enumerate(sources) if row.get("id") == source_id), -1)
    if index < 0:
        return {"ok": False, "error": "The selected balance was not found."}

    current = _normalize_source(sources[index], index)
    old_balance = _money(current.get("balance"))
    new_name = str(form.get("name") or "").strip()
    if not new_name:
        return {"ok": False, "error": "Insert a name for the gift card / buono sconto."}
    new_balance = _money(form.get("balance"))

    current.update({
        "name": new_name,
        "kind": _normalize_kind(form.get("kind")),
        "balance": new_balance,
        "aliases": _split_aliases(form.get("aliases")),
        "is_active": _truthy(form.get("is_active"), default=True),
        "updated_at": _now(),
    })
    if current["is_active"]:
        current["archived_at"] = ""
    elif not current.get("archived_at"):
        current["archived_at"] = _now()

    sources[index] = _normalize_source(current, index)
    events = list(payload.get("events") or [])
    if abs(new_balance - old_balance) >= 0.005:
        events.append(_balance_event(
            sources[index],
            event_type="adjust",
            amount=round(new_balance - old_balance, 2),
            balance_before=old_balance,
            balance_after=new_balance,
        ))
    payload["sources"] = sources
    payload["events"] = events[-1000:]
    save_discount_balances(payload, user_id=user_id)
    return {"ok": True, "message": f"{sources[index]['name']} updated.", "source": sources[index]}


def archive_discount_source(source_id: str, *, archived: bool = True, user_id: str | None = None) -> dict[str, Any]:
    source_id = str(source_id or "").strip()
    if not source_id:
        return {"ok": False, "error": "Missing balance id."}
    payload = load_discount_balances(user_id=user_id)
    sources = list(payload.get("sources") or [])
    index = next((idx for idx, row in enumerate(sources) if row.get("id") == source_id), -1)
    if index < 0:
        return {"ok": False, "error": "The selected balance was not found."}
    source = _normalize_source(sources[index], index)
    source["is_active"] = not archived
    source["updated_at"] = _now()
    source["archived_at"] = _now() if archived else ""
    sources[index] = _normalize_source(source, index)

    events = list(payload.get("events") or [])
    events.append(_balance_event(
        sources[index],
        event_type="archive" if archived else "restore",
        amount=0.0,
        balance_before=_money(sources[index].get("balance")),
        balance_after=_money(sources[index].get("balance")),
    ))
    payload["sources"] = sources
    payload["events"] = events[-1000:]
    save_discount_balances(payload, user_id=user_id)
    verb = "archived" if archived else "restored"
    return {"ok": True, "message": f"{sources[index]['name']} {verb}."}

def load_discount_balances(user_id: str | None = None) -> dict[str, Any]:
    payload = read_json_secure(_discount_balances_path(user_id), default=None, user_id=user_id)
    return _normalize_payload(payload)


def save_discount_balances(payload: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    normalized = _normalize_payload(payload)
    normalized["updated_at"] = _now()
    write_json_secure(_discount_balances_path(user_id), normalized, user_id=user_id)
    return normalized


def discount_source_options_for_forms(user_id: str | None = None) -> list[dict[str, Any]]:
    payload = load_discount_balances(user_id=user_id)
    options: list[dict[str, Any]] = []
    for source in payload.get("sources", []):
        if not source.get("is_active", True):
            continue
        balance = _money(source.get("balance"))
        if balance <= 0:
            continue
        aliases = [str(alias or "").strip() for alias in source.get("aliases", []) if str(alias or "").strip()]
        match_keys = _source_match_keys(source)
        options.append({
            "id": source.get("id", ""),
            "value": source.get("id", ""),
            "name": source.get("name", ""),
            "label": source_label(source),
            "kind": source.get("kind", SOURCE_KIND_GIFT_CARD),
            "kind_label": KIND_LABELS.get(source.get("kind"), "Stored discount balance"),
            "balance": balance,
            "balance_display": f"{balance:.2f}",
            "aliases": aliases,
            "match_keys": match_keys,
            "display_order": int(_to_int(source.get("display_order"), 1000) or 1000),
        })
    return sorted(options, key=lambda item: (item.get("display_order", 1000), str(item.get("name") or "").lower()))


def find_matching_discount_source(
    *,
    category: str = "",
    sub_category: str = "",
    description: str = "",
    user_id: str | None = None,
) -> dict[str, Any] | None:
    haystack = normalize_match_text(" ".join([category or "", sub_category or "", description or ""]))
    if not haystack:
        return None
    for source in discount_source_options_for_forms(user_id=user_id):
        for key in source.get("match_keys", []):
            if key and (key == haystack or key in haystack or haystack in key):
                return source
    return None


def validate_discount_source_form(form: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    if not form_uses_discount_source(form):
        return {"ok": True}

    requested = requested_discount_source_amount(form)
    if requested <= 0:
        return {"ok": False, "error": "Insert the gift card / buono sconto amount you want to use."}

    source_id = str(form.get("receipt_discount_source_id") or "").strip()
    if not source_id:
        return {"ok": False, "error": "Choose a gift card / buono sconto balance, or create a new one."}

    if source_id == NEW_SOURCE_SENTINEL:
        name = str(form.get("receipt_new_discount_source_name") or "").strip()
        if not name:
            return {"ok": False, "error": "Insert the name of the new gift card / buono sconto balance."}
        starting_balance = _money(form.get("receipt_new_discount_source_balance")) or requested
        if starting_balance <= 0:
            return {"ok": False, "error": "Insert the starting balance for the new gift card / buono sconto."}
        return {"ok": True}

    source = discount_source_by_id(source_id, user_id=user_id)
    if not source:
        return {"ok": False, "error": "The selected gift card / buono sconto balance was not found."}
    if not source.get("is_active", True):
        return {"ok": False, "error": "The selected gift card / buono sconto balance is archived."}
    if _money(source.get("balance")) <= 0:
        return {"ok": False, "error": f"{source.get('name') or 'Selected balance'} has no remaining balance."}
    return {"ok": True}


def discount_source_preview_from_form(form: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    if not form_uses_discount_source(form):
        return {"uses_source": False, "amount": 0.0}

    source_id = str(form.get("receipt_discount_source_id") or "").strip()
    requested = requested_discount_source_amount(form)
    explicit_applied = _money(form.get("receipt_discount_source_applied_amount"))
    explicit_before = _money(form.get("receipt_discount_source_balance_before"))
    explicit_after = _money(form.get("receipt_discount_source_balance_after"))
    explicit_name = str(form.get("receipt_discount_source_name") or "").strip()
    explicit_kind = _normalize_kind(form.get("receipt_discount_source_kind"))

    if explicit_applied > 0 and (explicit_name or source_id):
        return {
            "uses_source": True,
            "source_id": source_id,
            "source_name": explicit_name or source_id,
            "source_kind": explicit_kind,
            "source_kind_label": KIND_LABELS.get(explicit_kind, "Stored discount balance"),
            "requested_amount": requested or explicit_applied,
            "amount": explicit_applied,
            "balance_before": explicit_before,
            "balance_after": explicit_after,
        }

    if source_id == NEW_SOURCE_SENTINEL:
        name = str(form.get("receipt_new_discount_source_name") or "").strip()
        kind = _normalize_kind(form.get("receipt_new_discount_source_kind"))
        starting_balance = _money(form.get("receipt_new_discount_source_balance")) or requested
        amount = min(requested, starting_balance)
        return {
            "uses_source": True,
            "source_id": NEW_SOURCE_SENTINEL,
            "source_name": name or "New stored balance",
            "source_kind": kind,
            "source_kind_label": KIND_LABELS.get(kind, "Stored discount balance"),
            "requested_amount": requested,
            "amount": amount,
            "balance_before": starting_balance,
            "balance_after": max(0.0, starting_balance - amount),
        }

    source = discount_source_by_id(source_id, user_id=user_id)
    if not source:
        return {"uses_source": True, "source_id": source_id, "amount": 0.0}
    balance = _money(source.get("balance"))
    amount = min(requested, balance)
    return {
        "uses_source": True,
        "source_id": source.get("id", ""),
        "source_name": source.get("name", ""),
        "source_kind": source.get("kind", SOURCE_KIND_GIFT_CARD),
        "source_kind_label": KIND_LABELS.get(source.get("kind"), "Stored discount balance"),
        "requested_amount": requested,
        "amount": amount,
        "balance_before": balance,
        "balance_after": max(0.0, balance - amount),
    }


def apply_discount_source_from_form(
    form: Mapping[str, Any],
    tx: Mapping[str, Any] | None = None,
    *,
    transaction_uid: str = "",
    user_id: str | None = None,
) -> dict[str, Any]:
    if not form_uses_discount_source(form):
        return {"ok": True, "applied": False}

    validation = validate_discount_source_form(form, user_id=user_id)
    if not validation.get("ok"):
        return validation

    payload = load_discount_balances(user_id=user_id)
    sources = list(payload.get("sources") or [])
    source_id = str(form.get("receipt_discount_source_id") or "").strip()
    requested = requested_discount_source_amount(form)

    if source_id == NEW_SOURCE_SENTINEL:
        source = _source_from_new_form(form, index=len(sources), requested_amount=requested)
        sources.append(source)
        source_index = len(sources) - 1
    else:
        source_index = next((idx for idx, row in enumerate(sources) if row.get("id") == source_id), -1)
        if source_index < 0:
            return {"ok": False, "error": "The selected gift card / buono sconto balance was not found."}
        source = dict(sources[source_index])

    balance_before = _money(source.get("balance"))
    applied = min(requested, balance_before)
    balance_after = round(max(0.0, balance_before - applied), 2)
    if applied <= 0:
        return {"ok": False, "error": f"{source.get('name') or 'Selected balance'} has no remaining balance."}

    source["balance"] = balance_after
    source["updated_at"] = _now()
    if balance_after <= 0 and str(form.get("receipt_archive_empty_discount_source") or "").strip().lower() in {"1", "true", "yes", "on"}:
        source["is_active"] = False
        source["archived_at"] = _now()
    sources[source_index] = _normalize_source(source, source_index)

    event = {
        "id": uuid.uuid4().hex,
        "source_id": source.get("id", ""),
        "source_name": source.get("name", ""),
        "source_kind": source.get("kind", SOURCE_KIND_GIFT_CARD),
        "event_type": "use",
        "amount": applied,
        "requested_amount": requested,
        "balance_before": balance_before,
        "balance_after": balance_after,
        "transaction_uid": transaction_uid,
        "transaction_type": str((tx or {}).get("type") or "expense"),
        "transaction_date": str((tx or {}).get("date") or ""),
        "category": str((tx or {}).get("category") or ""),
        "sub_category": str((tx or {}).get("sub_category") or ""),
        "description": str((tx or {}).get("description") or ""),
        "created_at": _now(),
    }
    events = list(payload.get("events") or [])
    events.append(event)

    payload["sources"] = sources
    payload["events"] = events[-1000:]
    save_discount_balances(payload, user_id=user_id)

    return {
        "ok": True,
        "applied": True,
        "source": sources[source_index],
        "event": event,
        "applied_amount": applied,
        "requested_amount": requested,
        "balance_before": balance_before,
        "balance_after": balance_after,
        "receipt_form_fields": receipt_form_fields_from_application(sources[source_index], event),
    }


def receipt_form_fields_from_application(source: Mapping[str, Any], event: Mapping[str, Any]) -> dict[str, str]:
    applied = _money(event.get("amount"))
    return {
        "receipt_discount_type": "balance_source",
        "receipt_discount_value": f"{applied:.2f}",
        "receipt_discount_source_id": str(source.get("id") or ""),
        "receipt_discount_source_name": str(source.get("name") or ""),
        "receipt_discount_source_kind": str(source.get("kind") or SOURCE_KIND_GIFT_CARD),
        "receipt_discount_source_kind_label": KIND_LABELS.get(source.get("kind"), "Stored discount balance"),
        "receipt_discount_source_applied_amount": f"{applied:.2f}",
        "receipt_discount_source_requested_amount": f"{_money(event.get('requested_amount')):.2f}",
        "receipt_discount_source_balance_before": f"{_money(event.get('balance_before')):.2f}",
        "receipt_discount_source_balance_after": f"{_money(event.get('balance_after')):.2f}",
        "receipt_discount_source_event_id": str(event.get("id") or ""),
    }


def discount_source_by_id(source_id: str, user_id: str | None = None) -> dict[str, Any] | None:
    wanted = str(source_id or "").strip()
    if not wanted:
        return None
    for source in load_discount_balances(user_id=user_id).get("sources", []):
        if source.get("id") == wanted:
            return source
    return None


def form_uses_discount_source(form: Mapping[str, Any]) -> bool:
    discount_type = str(form.get("receipt_discount_type") or "").strip().lower()
    if discount_type == "balance_source":
        return True
    return str(form.get("receipt_use_discount_source") or "").strip().lower() in {"1", "true", "yes", "on"}


def requested_discount_source_amount(form: Mapping[str, Any]) -> float:
    for key in ("receipt_discount_source_amount", "receipt_discount_value", "receipt_discount_source_applied_amount"):
        amount = _money(form.get(key))
        if amount > 0:
            return amount
    return 0.0


def source_label(source: Mapping[str, Any]) -> str:
    name = str(source.get("name") or source.get("id") or "Stored balance").strip()
    kind = KIND_LABELS.get(source.get("kind"), "Stored discount balance")
    balance = _money(source.get("balance"))
    return f"{name} — {kind} — € {balance:.2f}"


def normalize_match_text(value: str) -> str:
    text = str(value or "").lower().strip()
    text = re.sub(r"[^a-z0-9àèéìòùç]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _source_match_keys(source: Mapping[str, Any]) -> list[str]:
    values = [source.get("name"), source.get("id"), *(source.get("aliases") or [])]
    keys: list[str] = []
    for value in values:
        key = normalize_match_text(str(value or ""))
        if key and key not in keys:
            keys.append(key)
    return keys


def _source_from_new_form(form: Mapping[str, Any], *, index: int, requested_amount: float) -> dict[str, Any]:
    name = str(form.get("receipt_new_discount_source_name") or "").strip() or "Stored discount balance"
    kind = _normalize_kind(form.get("receipt_new_discount_source_kind"))
    starting_balance = _money(form.get("receipt_new_discount_source_balance")) or requested_amount
    aliases = _split_aliases(form.get("receipt_new_discount_source_aliases"))
    now = _now()
    return _normalize_source({
        "id": _unique_source_id(name),
        "name": name,
        "kind": kind,
        "balance": starting_balance,
        "initial_balance": starting_balance,
        "aliases": aliases,
        "is_active": True,
        "display_order": 1000 + index,
        "created_at": now,
        "updated_at": now,
        "archived_at": "",
    }, index)




def _source_for_page(source: Mapping[str, Any]) -> dict[str, Any]:
    row = _normalize_source(source)
    balance = _money(row.get("balance"))
    initial = _money(row.get("initial_balance"))
    row.update({
        "kind_label": KIND_LABELS.get(row.get("kind"), "Stored discount balance"),
        "balance_display": f"{balance:.2f}",
        "initial_balance_display": f"{initial:.2f}",
        "aliases_text": ", ".join(row.get("aliases") or []),
        "status_label": "Active" if row.get("is_active") else "Archived",
    })
    return row


def _event_for_page(event: Mapping[str, Any]) -> dict[str, Any]:
    row = dict(event or {})
    amount = _money(row.get("amount"))
    if str(row.get("event_type") or "") == "adjust":
        try:
            amount = round(float(str(row.get("amount") or 0).replace(",", ".")), 2)
        except (TypeError, ValueError):
            amount = 0.0
    before = _money(row.get("balance_before"))
    after = _money(row.get("balance_after"))
    row.update({
        "kind_label": KIND_LABELS.get(row.get("source_kind"), "Stored discount balance"),
        "amount_display": f"{amount:.2f}",
        "balance_before_display": f"{before:.2f}",
        "balance_after_display": f"{after:.2f}",
    })
    return row


def _balance_event(
    source: Mapping[str, Any],
    *,
    event_type: str,
    amount: float,
    balance_before: float,
    balance_after: float,
) -> dict[str, Any]:
    return {
        "id": uuid.uuid4().hex,
        "source_id": source.get("id", ""),
        "source_name": source.get("name", ""),
        "source_kind": source.get("kind", SOURCE_KIND_GIFT_CARD),
        "event_type": event_type,
        "amount": round(float(amount or 0), 2),
        "balance_before": round(_money(balance_before), 2),
        "balance_after": round(_money(balance_after), 2),
        "transaction_uid": "",
        "transaction_type": "",
        "transaction_date": "",
        "category": "",
        "sub_category": "",
        "description": "",
        "created_at": _now(),
    }


def _truthy(value: Any, *, default: bool = False) -> bool:
    if value in (None, ""):
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on", "active"}

def _normalize_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        payload = {}
    sources_raw = payload.get("sources") if isinstance(payload.get("sources"), list) else []
    sources = [_normalize_source(row, index) for index, row in enumerate(sources_raw) if isinstance(row, Mapping)]
    events = [dict(row) for row in payload.get("events", []) if isinstance(row, Mapping)] if isinstance(payload.get("events"), list) else []
    return {
        "schema_version": int(_to_int(payload.get("schema_version"), 1) or 1),
        "sources": sources,
        "events": events,
        "updated_at": str(payload.get("updated_at") or ""),
    }


def _normalize_source(source: Mapping[str, Any], index: int = 0) -> dict[str, Any]:
    row = deepcopy(dict(source or {}))
    name = str(row.get("name") or row.get("label") or row.get("id") or "Stored balance").strip() or "Stored balance"
    row["id"] = str(row.get("id") or _unique_source_id(name)).strip()
    row["name"] = name
    row["kind"] = _normalize_kind(row.get("kind"))
    row["balance"] = _money(row.get("balance"))
    row["initial_balance"] = _money(row.get("initial_balance")) or row["balance"]
    row["aliases"] = _split_aliases(row.get("aliases"))
    row["is_active"] = bool(row.get("is_active", True))
    row["display_order"] = int(_to_int(row.get("display_order"), 1000 + index) or 1000 + index)
    row["created_at"] = str(row.get("created_at") or "")
    row["updated_at"] = str(row.get("updated_at") or "")
    row["archived_at"] = str(row.get("archived_at") or "")
    return row


def _normalize_kind(value: Any) -> str:
    kind = str(value or SOURCE_KIND_GIFT_CARD).strip().lower()
    aliases = {
        "gift": SOURCE_KIND_GIFT_CARD,
        "giftcard": SOURCE_KIND_GIFT_CARD,
        "gift-card": SOURCE_KIND_GIFT_CARD,
        "gift_card": SOURCE_KIND_GIFT_CARD,
        "buono": SOURCE_KIND_BUONO_SCONTO,
        "buoni": SOURCE_KIND_BUONO_SCONTO,
        "buono_sconto": SOURCE_KIND_BUONO_SCONTO,
        "discount": SOURCE_KIND_BUONO_SCONTO,
        "reimbursement": SOURCE_KIND_BUONO_SCONTO,
        "rimborso": SOURCE_KIND_BUONO_SCONTO,
    }
    return aliases.get(kind, kind if kind in SOURCE_KINDS else SOURCE_KIND_GIFT_CARD)


def _split_aliases(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        raw = value
    else:
        raw = re.split(r"[,;\n]", str(value or ""))
    aliases: list[str] = []
    for item in raw:
        text = str(item or "").strip()
        if text and text not in aliases:
            aliases.append(text)
    return aliases


def _unique_source_id(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(name or "stored-balance").lower()).strip("-") or "stored-balance"
    return f"{slug}-{uuid.uuid4().hex[:8]}"


def _discount_balances_path(user_id: str | None = None):
    return user_data_path(DISCOUNT_BALANCES_FILENAME, user_id=user_id or get_current_user_id())


def _money(value: Any) -> float:
    try:
        return round(max(0.0, float(str(value or 0).replace(",", "."))), 2)
    except (TypeError, ValueError):
        return 0.0


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(str(value if value is not None else default)))
    except (TypeError, ValueError):
        return default


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
