from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any, Mapping

from money_manager.config.user_paths import get_current_user_id, user_data_path
from money_manager.security.secure_storage import read_json_secure, write_json_secure

RECEIPTS_FILENAME = "receipts.json"
DISCOUNT_NONE = "none"
DISCOUNT_PERCENT = "percent"
DISCOUNT_VOUCHER = "voucher"
DISCOUNT_BALANCE_SOURCE = "balance_source"
VALID_DISCOUNT_TYPES = {DISCOUNT_NONE, DISCOUNT_PERCENT, DISCOUNT_VOUCHER, DISCOUNT_BALANCE_SOURCE}


def load_receipts(user_id: str | None = None) -> dict[str, Any]:
    payload = read_json_secure(_receipts_path(user_id), default=None, user_id=user_id)
    if not isinstance(payload, dict):
        payload = {}
    receipts = payload.get("receipts")
    if not isinstance(receipts, dict):
        receipts = {}
    return {
        "schema_version": int(_to_int(payload.get("schema_version"), 1) or 1),
        "receipts": receipts,
        "updated_at": str(payload.get("updated_at") or ""),
    }


def save_receipts(payload: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    result = {
        "schema_version": 1,
        "receipts": dict(payload.get("receipts") or {}) if isinstance(payload, Mapping) else {},
        "updated_at": _now(),
    }
    write_json_secure(_receipts_path(user_id), result, user_id=user_id)
    return result


def receipt_for_transaction(tx: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    uid = transaction_uid_from_tx(tx)
    stored = {}
    if uid:
        stored = load_receipts(user_id=user_id).get("receipts", {}).get(uid, {}) or {}
    receipt = _default_receipt_from_transaction(tx)
    if isinstance(stored, Mapping):
        receipt = _merge_receipt(receipt, stored)
    return finalize_receipt(receipt, tx)


def receipt_for_uid(transaction_uid: str, tx: Mapping[str, Any] | None = None, user_id: str | None = None) -> dict[str, Any]:
    tx = dict(tx or {})
    if transaction_uid and not tx.get("transaction_uid"):
        tx["transaction_uid"] = transaction_uid
    stored = load_receipts(user_id=user_id).get("receipts", {}).get(str(transaction_uid or ""), {}) or {}
    receipt = _default_receipt_from_transaction(tx)
    if isinstance(stored, Mapping):
        receipt = _merge_receipt(receipt, stored)
    return finalize_receipt(receipt, tx)


def update_receipt_from_form(tx: Mapping[str, Any], form: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    uid = transaction_uid_from_tx(tx)
    if not uid:
        return {"ok": False, "error": "This transaction has no stable receipt id yet."}

    payload = load_receipts(user_id=user_id)
    receipts = dict(payload.get("receipts") or {})
    receipt = receipt_from_form(tx, form)
    receipts[uid] = receipt
    payload["receipts"] = receipts
    save_receipts(payload, user_id=user_id)
    return {"ok": True, "receipt": finalize_receipt(receipt, tx), "sync_amount": _truthy(form.get("receipt_sync_amount"))}




def receipt_form_has_items(form: Mapping[str, Any]) -> bool:
    """Return true when the add/edit form contains a real receipt item list."""
    names = _form_list(form, "receipt_item_name")
    prices = _form_list(form, "receipt_item_unit_price")
    qtys = _form_list(form, "receipt_item_qty")
    return any(str(v or "").strip() for v in [*names, *prices, *qtys])


def receipt_total_from_form(tx: Mapping[str, Any], form: Mapping[str, Any]) -> float:
    """Calculate the transaction amount from receipt rows and discount."""
    receipt = finalize_receipt(receipt_from_form(tx, form), tx)
    return float(receipt.get("total", 0.0) or 0.0)


def save_receipt_for_saved_transaction(
    transaction_type: str,
    transaction_id: int | str,
    tx: Mapping[str, Any],
    form: Mapping[str, Any],
    user_id: str | None = None,
) -> dict[str, Any]:
    """Persist receipt metadata for a newly-created CSV transaction.

    Receipt items stay in receipts.json, keyed by transaction_uid. The transaction
    CSV keeps only the final total amount, so old transaction calculations remain
    compatible and fast.
    """
    from money_manager.domain.transaction import make_transaction_uid

    tx_type = str(transaction_type or tx.get("type") or "").strip().lower()
    tx_id = str(transaction_id or tx.get("id") or tx.get("csv_id") or "").strip()
    uid = make_transaction_uid(tx_type, tx_id) if tx_type and tx_id else ""
    if not uid:
        return {"ok": False, "error": "Missing saved transaction id for receipt."}

    tx_for_receipt = dict(tx or {})
    tx_for_receipt.update({
        "type": tx_type,
        "id": tx_id,
        "csv_id": tx_id,
        "transaction_uid": uid,
    })
    return update_receipt_from_form(tx_for_receipt, form, user_id=user_id)


def receipt_from_form(tx: Mapping[str, Any], form: Mapping[str, Any]) -> dict[str, Any]:
    base = _default_receipt_from_transaction(tx)
    items = []
    names = _form_list(form, "receipt_item_name")
    qtys = _form_list(form, "receipt_item_qty")
    unit_prices = _form_list(form, "receipt_item_unit_price")
    notes = _form_list(form, "receipt_item_note")
    max_len = max(len(names), len(qtys), len(unit_prices), len(notes), 0)
    for index in range(max_len):
        name = _at(names, index).strip() or f"Item {index + 1:03d}"
        qty = _positive_float(_at(qtys, index), default=1.0)
        unit_price = _money(_at(unit_prices, index))
        if unit_price <= 0 and not name:
            continue
        line_total = round(qty * unit_price, 2)
        if not name and line_total <= 0:
            continue
        items.append({
            "name": name,
            "qty": qty,
            "unit_price": round(unit_price, 2),
            "line_total": line_total,
            "note": _at(notes, index).strip(),
        })

    if not items:
        items = deepcopy(base["items"])

    discount_type = str(form.get("receipt_discount_type") or DISCOUNT_NONE).strip().lower()
    if discount_type not in VALID_DISCOUNT_TYPES:
        discount_type = DISCOUNT_NONE
    discount_value = _money(form.get("receipt_discount_value"))
    discount_source = {}
    if discount_type == DISCOUNT_PERCENT:
        discount_value = max(0.0, min(100.0, discount_value))
    elif discount_type == DISCOUNT_BALANCE_SOURCE:
        try:
            from money_manager.services.discount_balance_service import discount_source_preview_from_form

            source_preview = discount_source_preview_from_form(form)
        except Exception:
            source_preview = {"uses_source": True, "amount": discount_value}
        discount_value = _money(source_preview.get("amount")) or discount_value
        discount_source = {
            "id": str(source_preview.get("source_id") or form.get("receipt_discount_source_id") or "").strip(),
            "name": str(source_preview.get("source_name") or form.get("receipt_discount_source_name") or "").strip(),
            "kind": str(source_preview.get("source_kind") or form.get("receipt_discount_source_kind") or "").strip(),
            "kind_label": str(source_preview.get("source_kind_label") or form.get("receipt_discount_source_kind_label") or "").strip(),
            "requested_amount": round(_money(source_preview.get("requested_amount") or form.get("receipt_discount_source_requested_amount") or discount_value), 2),
            "applied_amount": round(discount_value, 2),
            "balance_before": round(_money(source_preview.get("balance_before") or form.get("receipt_discount_source_balance_before")), 2),
            "balance_after": round(_money(source_preview.get("balance_after") or form.get("receipt_discount_source_balance_after")), 2),
            "event_id": str(form.get("receipt_discount_source_event_id") or "").strip(),
        }
    elif discount_type == DISCOUNT_NONE:
        discount_value = 0.0

    receipt = {
        "transaction_uid": transaction_uid_from_tx(tx),
        "merchant": str(form.get("receipt_merchant") or base.get("merchant") or "").strip(),
        "purchased_at": str(form.get("receipt_purchased_at") or base.get("purchased_at") or "").strip(),
        "card_label": str(form.get("receipt_card_label") or base.get("card_label") or "").strip(),
        "card_last4": str(form.get("receipt_card_last4") or base.get("card_last4") or "").strip()[-4:],
        "card_network": str(form.get("receipt_card_network") or base.get("card_network") or "").strip(),
        "account_label": str(form.get("receipt_account_label") or base.get("account_label") or "").strip(),
        "items": items,
        "discount_type": discount_type,
        "discount_value": round(discount_value, 2),
        "notes": str(form.get("receipt_notes") or "").strip(),
        "updated_at": _now(),
    }
    if discount_source:
        receipt["discount_source"] = discount_source
    return receipt


def finalize_receipt(receipt: Mapping[str, Any], tx: Mapping[str, Any] | None = None) -> dict[str, Any]:
    tx = tx or {}
    result = deepcopy(dict(receipt or {}))
    items = []
    for index, row in enumerate(result.get("items") or []):
        if not isinstance(row, Mapping):
            continue
        name = str(row.get("name") or f"Item {index + 1:03d}").strip() or f"Item {index + 1:03d}"
        qty = _positive_float(row.get("qty"), default=1.0)
        unit_price = _money(row.get("unit_price"))
        line_total = _money(row.get("line_total")) or round(qty * unit_price, 2)
        items.append({
            "name": name,
            "qty": qty,
            "qty_display": _qty_display(qty),
            "unit_price": round(unit_price, 2),
            "unit_price_display": f"{unit_price:.2f}",
            "line_total": round(line_total, 2),
            "line_total_display": f"{line_total:.2f}",
            "note": str(row.get("note") or "").strip(),
        })
    if not items:
        default = _default_receipt_from_transaction(tx)
        items = default["items"]

    subtotal = round(sum(_money(item.get("line_total")) for item in items), 2)
    discount_type = str(result.get("discount_type") or DISCOUNT_NONE).strip().lower()
    if discount_type not in VALID_DISCOUNT_TYPES:
        discount_type = DISCOUNT_NONE
    discount_value = _money(result.get("discount_value"))
    discount_source = result.get("discount_source") if isinstance(result.get("discount_source"), Mapping) else {}
    if discount_type == DISCOUNT_PERCENT:
        discount_value = max(0.0, min(100.0, discount_value))
        discount_amount = round(subtotal * discount_value / 100.0, 2)
        discount_label = f"{discount_value:g}% off"
    elif discount_type == DISCOUNT_VOUCHER:
        discount_amount = min(subtotal, round(discount_value, 2))
        discount_label = f"Voucher € {discount_amount:.2f}"
    elif discount_type == DISCOUNT_BALANCE_SOURCE:
        discount_amount = min(subtotal, round(discount_value, 2))
        source_name = str(discount_source.get("name") or "Stored balance").strip()
        source_kind = str(discount_source.get("kind_label") or _discount_source_kind_label(discount_source.get("kind"))).strip()
        discount_label = f"{source_kind}: {source_name} — € {discount_amount:.2f}"
    else:
        discount_value = 0.0
        discount_amount = 0.0
        discount_label = "No discount"
        discount_source = {}
    total = round(max(0.0, subtotal - discount_amount), 2)

    result.update({
        "transaction_uid": result.get("transaction_uid") or transaction_uid_from_tx(tx),
        "merchant": str(result.get("merchant") or tx.get("description") or tx.get("category") or "Receipt").strip(),
        "purchased_at": str(result.get("purchased_at") or tx.get("date") or "").strip(),
        "card_label": str(result.get("card_label") or tx.get("payment_method_name_snapshot") or tx.get("payment_method") or "").strip(),
        "card_last4": str(result.get("card_last4") or "").strip()[-4:],
        "card_network": str(result.get("card_network") or "").strip(),
        "account_label": str(result.get("account_label") or tx.get("account_name_snapshot") or tx.get("account_label") or tx.get("account") or "").strip(),
        "items": items,
        "discount_type": discount_type,
        "discount_value": round(discount_value, 2),
        "discount_amount": discount_amount,
        "discount_label": discount_label,
        "discount_source": _finalize_discount_source(discount_source, discount_amount) if discount_source else {},
        "discount_source_label": _discount_source_label(discount_source, discount_amount) if discount_source else "",
        "subtotal": subtotal,
        "subtotal_display": f"{subtotal:.2f}",
        "total": total,
        "total_display": f"{total:.2f}",
        "item_count": len(items),
        "notes": str(result.get("notes") or "").strip(),
        "has_custom_receipt": bool(result.get("updated_at")),
    })
    return result


def transaction_uid_from_tx(tx: Mapping[str, Any] | None) -> str:
    tx = tx or {}
    uid = str(tx.get("transaction_uid") or "").strip()
    if uid:
        return uid
    tx_type = str(tx.get("type") or "").strip().lower()
    tx_id = str(tx.get("csv_id") or tx.get("id") or "").strip()
    if tx_type and tx_id:
        from money_manager.domain.transaction import make_transaction_uid

        return make_transaction_uid(tx_type, tx_id)
    return ""


def _default_receipt_from_transaction(tx: Mapping[str, Any] | None) -> dict[str, Any]:
    tx = tx or {}
    amount = _money(tx.get("amount"))
    name = str(tx.get("sub_category") or tx.get("category") or tx.get("description") or "Item 001").strip() or "Item 001"
    merchant = str(tx.get("description") or tx.get("category") or "Receipt").strip() or "Receipt"
    card_details = _payment_method_card_details(tx)
    return {
        "transaction_uid": transaction_uid_from_tx(tx),
        "merchant": merchant,
        "purchased_at": str(tx.get("created_at") or tx.get("date") or "").strip(),
        "card_label": str(card_details.get("label") or tx.get("payment_method_name_snapshot") or tx.get("payment_channel_name_snapshot") or tx.get("payment_method") or "").strip(),
        "card_last4": str(card_details.get("last4") or "").strip()[-4:],
        "card_network": str(card_details.get("network") or "").strip(),
        "account_label": str(tx.get("account_name_snapshot") or tx.get("account_label") or tx.get("account") or "").strip(),
        "items": [{
            "name": name if name else "Item 001",
            "qty": 1.0,
            "unit_price": amount,
            "line_total": amount,
            "note": "",
        }],
        "discount_type": DISCOUNT_NONE,
        "discount_value": 0.0,
        "discount_source": {},
        "notes": "",
        "updated_at": "",
    }


def _payment_method_card_details(tx: Mapping[str, Any]) -> dict[str, str]:
    method_id = str(
        tx.get("payment_method_id")
        or tx.get("payment_channel_method_id_snapshot")
        or tx.get("payment_method_id_snapshot")
        or ""
    ).strip()
    if not method_id:
        return {}
    try:
        from money_manager.services.payment_method_service import payment_method_by_id

        method = payment_method_by_id(method_id, include_archived=True) or {}
    except Exception:
        method = {}
    if not isinstance(method, Mapping):
        return {}
    metadata = method.get("metadata") if isinstance(method.get("metadata"), Mapping) else {}
    card_meta = metadata.get("card") if isinstance(metadata.get("card"), Mapping) else {}
    return {
        "label": str(method.get("name") or method.get("label") or tx.get("payment_method_name_snapshot") or method_id or ""),
        "last4": str(card_meta.get("last4") or method.get("card_last4") or ""),
        "network": str(card_meta.get("network") or method.get("card_network") or ""),
    }



def _discount_source_kind_label(kind: Any) -> str:
    text = str(kind or "").strip().lower()
    if text == "buono_sconto":
        return "Buono sconto / reimbursement"
    if text == "gift_card":
        return "Gift card"
    return "Stored discount balance"


def _finalize_discount_source(source: Mapping[str, Any], applied_amount: float) -> dict[str, Any]:
    if not isinstance(source, Mapping):
        return {}
    kind = str(source.get("kind") or "").strip()
    kind_label = str(source.get("kind_label") or _discount_source_kind_label(kind)).strip()
    name = str(source.get("name") or source.get("id") or "Stored balance").strip()
    return {
        "id": str(source.get("id") or "").strip(),
        "name": name,
        "kind": kind,
        "kind_label": kind_label,
        "requested_amount": round(_money(source.get("requested_amount") or applied_amount), 2),
        "applied_amount": round(_money(source.get("applied_amount") or applied_amount), 2),
        "applied_amount_display": f"{_money(source.get('applied_amount') or applied_amount):.2f}",
        "balance_before": round(_money(source.get("balance_before")), 2),
        "balance_before_display": f"{_money(source.get('balance_before')):.2f}",
        "balance_after": round(_money(source.get("balance_after")), 2),
        "balance_after_display": f"{_money(source.get('balance_after')):.2f}",
        "event_id": str(source.get("event_id") or "").strip(),
        "label": _discount_source_label(source, applied_amount),
    }


def _discount_source_label(source: Mapping[str, Any], applied_amount: float) -> str:
    if not isinstance(source, Mapping):
        return ""
    name = str(source.get("name") or source.get("id") or "Stored balance").strip()
    kind_label = str(source.get("kind_label") or _discount_source_kind_label(source.get("kind"))).strip()
    after = _money(source.get("balance_after"))
    label = f"{kind_label}: {name} used € {applied_amount:.2f}"
    if source.get("balance_after") not in (None, ""):
        label += f" · remaining € {after:.2f}"
    return label

def _merge_receipt(default: Mapping[str, Any], stored: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(dict(default or {}))
    for key, value in dict(stored or {}).items():
        if key == "items" and isinstance(value, list):
            result[key] = deepcopy(value)
        elif key != "items":
            result[key] = value
    return result


def _receipts_path(user_id: str | None = None):
    return user_data_path(RECEIPTS_FILENAME, user_id=user_id or get_current_user_id())


def _form_list(form: Mapping[str, Any], key: str) -> list[str]:
    if hasattr(form, "getlist"):
        return [str(value or "") for value in form.getlist(key)]
    value = form.get(key, []) if isinstance(form, Mapping) else []
    if isinstance(value, (list, tuple)):
        return [str(item or "") for item in value]
    return [str(value or "")] if value not in (None, "") else []


def _at(values: list[str], index: int) -> str:
    return values[index] if index < len(values) else ""


def _money(value) -> float:
    try:
        return round(max(0.0, float(str(value or 0).replace(",", "."))), 2)
    except (TypeError, ValueError):
        return 0.0


def _positive_float(value, default: float = 1.0) -> float:
    try:
        parsed = float(str(value or default).replace(",", "."))
    except (TypeError, ValueError):
        parsed = default
    return max(0.0, parsed)


def _to_int(value, default: int = 0) -> int:
    try:
        return int(float(str(value or default)))
    except (TypeError, ValueError):
        return default


def _qty_display(value: float) -> str:
    if abs(value - int(value)) < 0.000001:
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _truthy(value) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
