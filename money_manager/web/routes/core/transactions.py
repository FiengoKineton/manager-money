from datetime import date
import json

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, url_for

from money_manager.config import TRANSACTION_TYPES
from money_manager.domain.transaction import TransactionInput, make_transaction_uid
from money_manager.services.analytics_service import apply_transaction_filters
from money_manager.services.calculation_service import cached_context
from money_manager.services.account_scope_service import transactions_for_scope
from money_manager.services.category_service import category_context
from money_manager.services.custom_category_service import add_custom_category
from money_manager.services.category_icon_service import set_category_icon
from money_manager.services.currency_service import currency_options_for_forms
from money_manager.services.quick_log_service import handle_quick_log, quick_log_context
from money_manager.services.payment_form_service import payment_form_context
from money_manager.services.discount_balance_service import (
    apply_discount_source_from_form,
    discount_source_options_for_forms,
    find_matching_discount_source,
    validate_discount_source_form,
)
from money_manager.utils.stats import summary_totals
from money_manager.services.transaction_window_service import (
    split_transactions_at,
    totals_with_initial_conditions,
    transaction_default_date_range,
    transaction_initial_conditions_for_frame,
)
from money_manager.web.transaction_filter_state import resolve_transaction_filter_state
from money_manager.web.context import resolve_request_scope, scope_template_context
from money_manager.services.receipt_service import (
    receipt_for_transaction,
    receipt_form_has_items,
    receipt_total_from_form,
    save_receipt_for_saved_transaction,
    update_receipt_from_form,
)
from money_manager.services.bill_scan_service import scan_bill_files
from money_manager.services.transaction_service import (
    delete_existing_transaction,
    load_transactions,
    prepare_transactions_for_display,
    account_balances_for_preview,
    main_net_for_preview,
    paypal_balance,
    save_new_transaction,
    transaction_detail_context,
    update_existing_transaction,
    delay_existing_transaction,
)

bp = Blueprint("transactions", __name__)

DEFAULT_TRANSACTION_PAGE_SIZE = 50
MAX_TRANSACTION_PAGE_SIZE = 200
NEW_CATEGORY_SENTINEL = "__new_category__"


def _clean_form_text(value) -> str:
    return " ".join(str(value or "").strip().split())


def _apply_inline_custom_category(posted_form) -> str:
    """Convert the inline “create category” option into a real saved category.

    Returns an empty string on success, otherwise a UI-friendly error message.
    """
    transaction_type = posted_form.get("type", "expense")
    selected_category = _clean_form_text(posted_form.get("category", ""))
    custom_name = _clean_form_text(posted_form.get("custom_category_name", ""))
    custom_icon = _clean_form_text(posted_form.get("custom_category_icon", ""))

    if selected_category != NEW_CATEGORY_SENTINEL:
        return ""
    if not custom_name:
        return "Write the new category name, or choose an existing category."

    try:
        add_custom_category(transaction_type, custom_name)
        if custom_icon:
            set_category_icon(custom_name, custom_icon, transaction_type)
    except ValueError as exc:
        return str(exc)

    posted_form["category"] = custom_name
    return ""


def _positive_int_arg(name: str, default: int, *, minimum: int = 1, maximum: int | None = None) -> int:
    try:
        value = int(request.args.get(name, default))
    except (TypeError, ValueError):
        value = default
    value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value



@bp.route("/transactions")
def transactions_page():
    selected_scope = resolve_request_scope(request)
    scope_key = selected_scope["scope"]

    start_default, end_default = transaction_default_date_range()
    filter_state = resolve_transaction_filter_state(request.args, start_default, end_default, TRANSACTION_TYPES)

    page_size = _positive_int_arg("page_size", DEFAULT_TRANSACTION_PAGE_SIZE, minimum=1, maximum=MAX_TRANSACTION_PAGE_SIZE)

    params = _transaction_cache_params(scope_key, filter_state)
    params.update({"page": 1, "page_size": page_size})

    context = cached_context(
        "transaction_table_view_v3",
        lambda: _build_transactions_page_context(scope_key, filter_state, page=1, page_size=page_size),
        params=params,
    )

    return render_template(
        "core/transactions.html",
        **context,
        **scope_template_context(selected_scope),
    )


def _transaction_cache_params(scope_key: str, filter_state: dict) -> dict:
    return {
        "scope": scope_key,
        "start": filter_state["start"],
        "end": filter_state["end"],
        "types": tuple(filter_state["types"]),
        "categories": tuple(filter_state["categories"]),
        "query": filter_state["query"],
        "amount_min": filter_state["amount_min"],
        "amount_max": filter_state["amount_max"],
        "has_effective_filters": bool(filter_state.get("has_effective_filters")),
    }


def _filtered_transactions_for_page(scope_key: str, filter_state: dict):
    df = load_transactions()
    main_df = transactions_for_scope(df, scope_key)

    filtered = apply_transaction_filters(
        main_df,
        filter_state["start"],
        filter_state["end"],
        filter_state["types"],
        filter_state["categories"],
        filter_state["query"],
        filter_state["amount_min"],
        filter_state["amount_max"],
    )
    return main_df, filtered


def _slice_transactions_for_display(filtered, *, page: int, page_size: int) -> tuple[list[dict], int, int, bool]:
    total_rows = int(len(filtered))
    start_index = max(page - 1, 0) * page_size
    end_index = start_index + page_size
    visible = filtered.iloc[start_index:end_index].copy()
    visible = prepare_transactions_for_display(visible)
    return visible.to_dict(orient="records"), total_rows, start_index, end_index < total_rows


def _build_transactions_page_context(scope_key: str, filter_state: dict, *, page: int = 1, page_size: int = DEFAULT_TRANSACTION_PAGE_SIZE) -> dict:
    main_df, filtered = _filtered_transactions_for_page(scope_key, filter_state)

    start = filter_state["start"]
    end = filter_state["end"]
    types = filter_state["types"]
    categories = filter_state["categories"]
    query = filter_state["query"]
    amount_min = filter_state["amount_min"]
    amount_max = filter_state["amount_max"]
    has_effective_filters = bool(filter_state.get("has_effective_filters"))

    historical_df, _recent_df = split_transactions_at(main_df, start)
    initial_conditions = transaction_initial_conditions_for_frame(
        historical_df,
        scope=scope_key,
        start=start,
    )
    calculation_totals = summary_totals(filtered)
    if not has_effective_filters:
        calculation_totals = totals_with_initial_conditions(filtered, initial_conditions)

    rows, total_rows, _start_index, has_more = _slice_transactions_for_display(
        filtered,
        page=page,
        page_size=page_size,
    )
    all_categories = sorted(main_df["category"].dropna().unique().tolist()) if not main_df.empty and "category" in main_df.columns else []

    transaction_summary = {
        "count": total_rows,
        "shown_count": len(rows),
        "income": calculation_totals["income"],
        "expenses": calculation_totals["expenses"],
        "investments": calculation_totals["investments"],
        "net": calculation_totals["net"],
        "opening_net": calculation_totals.get("opening_net", 0.0),
        "recent_net": calculation_totals.get("recent_net", calculation_totals["net"]),
        "savings_rate": calculation_totals["savings_rate"],
        "scope_label": "selected filters" if has_effective_filters else "initial condition + rolling window",
        "uses_full_history_for_calculations": False,
        "uses_transaction_initial_conditions": not has_effective_filters,
        "initial_condition_rows": int(initial_conditions.get("historical_rows", 0) or 0),
    }

    return {
        # Real lazy loading: only the first page is rendered into the initial HTML.
        # Older versions also passed/rendered every hidden transaction, duplicated
        # for desktop and mobile, which made navigation slow and could trigger 504s.
        "transactions": rows,
        "transactions_initial": rows,
        "transaction_summary": transaction_summary,
        "transactions_total_count": total_rows,
        "transactions_shown_count": len(rows),
        "transactions_page": page,
        "transactions_page_size": page_size,
        "transactions_has_more": has_more,
        "start": start,
        "end": end,
        "active_types": types,
        "all_types": TRANSACTION_TYPES,
        "categories_selected": categories,
        "categories_all": all_categories,
        "q": query,
        "amount_min": amount_min,
        "amount_max": amount_max,
        "has_effective_filters": has_effective_filters,
        "has_non_date_filters": bool(filter_state.get("has_non_date_filters")),
        "uses_full_history_for_calculations": False,
        "uses_transaction_initial_conditions": not has_effective_filters,
        "visual_scope_label": filter_state.get("display_scope_label", "previous month + current month"),
        "transaction_window": {
            "start": start,
            "end": end,
            "opening_net": float(initial_conditions.get("opening_net", 0.0) or 0.0),
            "historical_rows": int(initial_conditions.get("historical_rows", 0) or 0),
        },
    }


@bp.get("/transactions/page")
def transactions_page_slice():
    selected_scope = resolve_request_scope(request)
    scope_key = selected_scope["scope"]

    start_default, end_default = transaction_default_date_range()
    filter_state = resolve_transaction_filter_state(request.args, start_default, end_default, TRANSACTION_TYPES)
    page = _positive_int_arg("page", 1, minimum=1)
    page_size = _positive_int_arg("page_size", DEFAULT_TRANSACTION_PAGE_SIZE, minimum=1, maximum=MAX_TRANSACTION_PAGE_SIZE)

    params = _transaction_cache_params(scope_key, filter_state)
    params.update({"page": page, "page_size": page_size})

    payload = cached_context(
        "transaction_table_page_v2",
        lambda: _build_transactions_page_slice(scope_key, filter_state, page=page, page_size=page_size),
        params=params,
    )
    return jsonify(payload)


def _build_transactions_page_slice(scope_key: str, filter_state: dict, *, page: int, page_size: int) -> dict:
    _main_df, filtered = _filtered_transactions_for_page(scope_key, filter_state)
    rows, total_rows, start_index, has_more = _slice_transactions_for_display(
        filtered,
        page=page,
        page_size=page_size,
    )
    return {
        "ok": True,
        "page": page,
        "page_size": page_size,
        "shown_count": min(start_index + len(rows), total_rows),
        "total_count": total_rows,
        "has_more": has_more,
        "desktop_html": render_template("core/_transaction_desktop_rows.html", transactions=rows),
        "phone_html": render_template("core/_transaction_phone_cards.html", transactions=rows),
    }


@bp.route("/add", methods=["GET", "POST"])
def add_transaction():
    form_values = {}
    form_error = ""

    quick_error = ""
    quick_message = request.args.get("quick_message", "")
    quick_values = {}

    if request.method == "POST" and request.form.get("action") == "quick_special_log":
        result = handle_quick_log(request.form)
        if result.get("ok"):
            return redirect(url_for("transactions.add_transaction", type=request.args.get("type", "expense"), special="1", quick_message=result.get("message", "Saved.")))
        quick_error = result.get("error", "The special log was not saved.")
        quick_values = request.form.to_dict()
        transaction_type = request.args.get("type", "expense")
    elif request.method == "POST":
        posted_form = request.form.copy()
        inline_category_error = _apply_inline_custom_category(posted_form)
        if inline_category_error:
            form_error = inline_category_error
            form_values = request.form.to_dict()
            transaction_type = posted_form.get("type", "expense")
        else:
            provisional_tx = {
                "type": posted_form.get("type", "expense"),
                "date": posted_form.get("date", ""),
                "category": posted_form.get("category", ""),
                "sub_category": posted_form.get("sub_category", ""),
                "description": posted_form.get("description", ""),
                "account": posted_form.get("account", ""),
                "account_id": posted_form.get("account_id", ""),
                "payment_method_id": posted_form.get("payment_method_id", ""),
                "amount": posted_form.get("amount", "0"),
            }
            source_validation = validate_discount_source_form(request.form) if receipt_form_has_items(request.form) else {"ok": True}
            if not source_validation.get("ok"):
                form_error = source_validation.get("error", "The selected gift card / buono sconto balance is not valid.")
                form_values = request.form.to_dict()
                transaction_type = posted_form.get("type", "expense")
            else:
                if receipt_form_has_items(request.form):
                    posted_form["amount"] = f"{receipt_total_from_form(provisional_tx, request.form):.2f}"
                    provisional_tx["amount"] = posted_form["amount"]

                tx_input = TransactionInput.from_form(posted_form)
                result = save_new_transaction(tx_input)
                if result.get("ok"):
                    tx_ids = result.get("transaction_ids") or []
                    if tx_ids and receipt_form_has_items(request.form):
                        receipt_tx = tx_input.as_dict()
                        receipt_tx.update({
                            "amount": f"{float(tx_input.amount or 0):.2f}",
                            "payment_method_id": tx_input.payment_method_id,
                            "account_id": tx_input.account_id,
                        })
                        receipt_form = posted_form.copy()
                        try:
                            tx_uid = make_transaction_uid(tx_input.type, tx_ids[0])
                            source_result = apply_discount_source_from_form(receipt_form, receipt_tx, transaction_uid=tx_uid)
                            if source_result.get("ok") and source_result.get("receipt_form_fields"):
                                for field_name, field_value in source_result["receipt_form_fields"].items():
                                    receipt_form[field_name] = field_value
                        except Exception:
                            current_app.logger.exception("Failed to apply receipt discount balance for transaction %s:%s", tx_input.type, tx_ids[0])
                        try:
                            save_receipt_for_saved_transaction(tx_input.type, tx_ids[0], receipt_tx, receipt_form)
                        except Exception:
                            current_app.logger.exception("Failed to save receipt for newly-created transaction %s:%s", tx_input.type, tx_ids[0])
                    scoped_account_id = posted_form.get("account_id") or request.args.get("account_id") or ""
                    return redirect(url_for("transactions.transactions_page", account_id=scoped_account_id) if scoped_account_id else url_for("transactions.transactions_page"))
                form_error = result.get("error", "The transaction was not saved.")
                form_values = request.form.to_dict()
                transaction_type = tx_input.type
    else:
        transaction_type = request.args.get("type", "expense")

    if transaction_type not in TRANSACTION_TYPES:
        transaction_type = "expense"

    show_special_log = request.args.get("special") == "1" or (request.method == "POST" and request.form.get("action") == "quick_special_log")
    special_context = quick_log_context() if show_special_log else {"quick_log_modes": [], "quick_log_context": {}}

    context = category_context(transaction_type)
    payment_context = payment_form_context(
        transaction_type=transaction_type,
        selected_account_id=form_values.get("account_id") or form_values.get("account") or request.args.get("account_id"),
        selected_payment_method_id=form_values.get("payment_method_id") or request.args.get("payment_method_id"),
    )
    currency_options = currency_options_for_forms()
    discount_source_options = discount_source_options_for_forms()
    suggested_discount_source = find_matching_discount_source(
        category=form_values.get("category", ""),
        sub_category=form_values.get("sub_category", ""),
        description=form_values.get("description", ""),
    )
    return render_template(
        "core/add_transaction.html",
        **context,
        **payment_context,
        today=date.today().isoformat(),
        currency_options=currency_options,
        currency_options_json=json.dumps(currency_options),
        discount_source_options=discount_source_options,
        discount_source_options_json=json.dumps(discount_source_options),
        suggested_discount_source=suggested_discount_source,
        paypal_balance=paypal_balance(),
        account_balances_json=json.dumps(account_balances_for_preview()),
        main_net_preview=main_net_for_preview(),
        form_error=form_error,
        form_values=form_values,
        quick_error=quick_error,
        quick_message=quick_message,
        quick_values=quick_values,
        show_special_log=show_special_log,
        **special_context,
    )


@bp.route("/receipt-scanner", methods=["GET", "POST"])
def receipt_scanner():
    """Upload PDF bills and convert them into editable expense drafts."""
    scan_result: dict = {"candidates": [], "errors": [], "ok": False}
    save_message = ""
    save_errors: list[str] = []
    selected_account_id = request.form.get("account_id") or request.args.get("account_id") or ""
    selected_payment_method_id = request.form.get("payment_method_id") or request.args.get("payment_method_id") or ""

    if request.method == "POST" and request.form.get("action") == "scan_bills":
        uploaded_files = request.files.getlist("bill_files")
        scan_result = scan_bill_files(uploaded_files, default_date=date.today().isoformat())
    elif request.method == "POST" and request.form.get("action") == "save_detected_bills":
        selected_account_id = request.form.get("account_id", "")
        selected_payment_method_id = request.form.get("payment_method_id", "")
        saved_count = 0
        candidate_count = _positive_int_form("candidate_count", 0, minimum=0, maximum=50)
        if request.form.get("confirm_expenses") != "1":
            save_errors.append("Confirm that the selected detected rows should be saved as expenses.")
            candidate_count = 0
        for index in range(candidate_count):
            if request.form.get(f"save_{index}") != "1":
                continue
            tx_form = {
                "type": "expense",
                "date": request.form.get(f"date_{index}", date.today().isoformat()),
                "category": request.form.get(f"category_{index}", ""),
                "sub_category": request.form.get(f"sub_category_{index}", ""),
                "amount": f"{_positive_money(request.form.get(f'amount_{index}')):.2f}",
                "account": "",
                "account_id": selected_account_id,
                "payment_method_id": selected_payment_method_id,
                "description": request.form.get(f"description_{index}", "PDF bill"),
                "currency": "EUR",
            }
            tx_input = TransactionInput.from_form(tx_form)
            if not tx_input.date:
                save_errors.append(f"Row {index + 1}: missing date.")
                continue
            if not tx_input.category:
                save_errors.append(f"Row {index + 1}: missing category.")
                continue
            if tx_input.amount <= 0:
                save_errors.append(f"Row {index + 1}: missing or invalid amount.")
                continue

            result = save_new_transaction(tx_input)
            if not result.get("ok"):
                save_errors.append(f"Row {index + 1}: {result.get('error') or 'not saved'}")
                continue

            saved_count += 1
            tx_ids = result.get("transaction_ids") or []
            if tx_ids:
                receipt_form = _receipt_scanner_form_for_index(index, request.form)
                receipt_tx = tx_input.as_dict()
                receipt_tx["amount"] = f"{float(tx_input.amount or 0):.2f}"
                try:
                    save_receipt_for_saved_transaction("expense", tx_ids[0], receipt_tx, receipt_form)
                except Exception:
                    current_app.logger.exception("Failed to save scanned receipt for expense %s", tx_ids[0])
                    save_errors.append(f"Row {index + 1}: expense saved, but receipt details were not attached.")
            else:
                save_errors.append(f"Row {index + 1}: expense was routed outside the transaction log, so receipt items were not attached.")

        if saved_count:
            save_message = f"Saved {saved_count} scanned expense{'s' if saved_count != 1 else ''}."
        if not saved_count and not save_errors:
            save_errors.append("Select at least one detected bill to save.")

    context = category_context("expense")
    payment_context = payment_form_context(
        transaction_type="expense",
        selected_account_id=selected_account_id,
        selected_payment_method_id=selected_payment_method_id,
    )
    template_context = {
        **context,
        **payment_context,
        "today": date.today().isoformat(),
        "scan_result": scan_result,
        "save_message": save_message,
        "save_errors": save_errors,
        "selected_account_id": selected_account_id,
        "selected_payment_method_id": selected_payment_method_id,
    }
    template_context["payment_form_json"] = payment_context.get("payment_form_json") or json.dumps(
        payment_context.get("payment_form", {}),
        ensure_ascii=False,
    )
    return render_template("core/receipt_scanner.html", **template_context)


def _positive_int_form(name: str, default: int, *, minimum: int = 0, maximum: int | None = None) -> int:
    try:
        value = int(request.form.get(name, default))
    except (TypeError, ValueError):
        value = default
    value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _positive_money(value) -> float:
    try:
        return round(max(0.0, float(str(value or 0).replace(",", "."))), 2)
    except (TypeError, ValueError):
        return 0.0


def _receipt_scanner_form_for_index(index: int, form) -> dict:
    try:
        items = json.loads(form.get(f"items_{index}") or "[]")
    except Exception:
        items = []
    if not isinstance(items, list):
        items = []

    names: list[str] = []
    qtys: list[str] = []
    unit_prices: list[str] = []
    notes: list[str] = []
    for row in items:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        qty = _positive_money(row.get("qty")) or 1.0
        unit = _positive_money(row.get("unit_price"))
        if unit <= 0:
            unit = _positive_money(row.get("line_total"))
        names.append(name)
        qtys.append(str(qty))
        unit_prices.append(f"{unit:.2f}")
        notes.append(str(row.get("note") or ""))

    if not names:
        names = [form.get(f"description_{index}", "PDF bill")]
        qtys = ["1"]
        unit_prices = [f"{_positive_money(form.get(f'amount_{index}')):.2f}"]
        notes = [""]

    return {
        "receipt_merchant": form.get(f"merchant_{index}", ""),
        "receipt_purchased_at": form.get(f"date_{index}", ""),
        "receipt_card_label": "",
        "receipt_card_last4": "",
        "receipt_card_network": "",
        "receipt_account_label": "",
        "receipt_item_name": names,
        "receipt_item_qty": qtys,
        "receipt_item_unit_price": unit_prices,
        "receipt_item_note": notes,
        "receipt_discount_type": form.get(f"discount_type_{index}", "none"),
        "receipt_discount_value": form.get(f"discount_value_{index}", "0"),
        "receipt_notes": form.get(f"notes_{index}", "Imported from PDF bill scanner"),
    }


@bp.route("/transaction/<int:row_index>/receipt")
def transaction_receipt_snippet(row_index: int):
    try:
        tx, _categories = transaction_detail_context(row_index)
    except LookupError:
        return jsonify({"ok": False, "error": "Transaction not found"}), 404
    except Exception:
        current_app.logger.exception("Failed to load transaction %s for receipt snippet", row_index)
        return jsonify({"ok": False, "error": "Receipt unavailable"}), 500

    try:
        receipt = tx.get("receipt") or receipt_for_transaction(tx)
    except Exception:
        current_app.logger.exception("Failed to load receipt for transaction %s", row_index)
        receipt = _fallback_receipt_from_transaction(tx)

    return jsonify({
        "ok": True,
        "transaction": {
            "row_index": row_index,
            "date": tx.get("date", ""),
            "amount": tx.get("amount", ""),
            "category": tx.get("category", ""),
            "description": tx.get("description", ""),
            "account": tx.get("account_name_snapshot") or tx.get("account_label") or tx.get("account") or "",
            "payment_method": tx.get("payment_method_name_snapshot") or tx.get("payment_method") or "",
        },
        "receipt": receipt,
    })


@bp.route("/transaction/<int:row_index>", methods=["GET", "POST"])
def transaction_detail(row_index: int):
    warning = ""
    if request.method == "POST":
        action = request.form.get("action")

        if action == "save_receipt":
            try:
                tx, _categories = transaction_detail_context(row_index)
            except LookupError:
                return f"Transaction {row_index} not found", 404
            result = update_receipt_from_form(tx, request.form)
            if result.get("ok"):
                if result.get("sync_amount"):
                    sync_form = dict(request.form)
                    sync_form["amount"] = f"{float(result.get('receipt', {}).get('total', tx.get('amount') or 0)):.2f}"
                    sync_form["date"] = tx.get("date", "")
                    sync_form["category"] = tx.get("category", "")
                    sync_form["sub_category"] = tx.get("sub_category", "")
                    sync_form["account"] = tx.get("account", "")
                    sync_form["account_id"] = tx.get("account_id", "")
                    sync_form["payment_method_id"] = tx.get("payment_method_id", "")
                    sync_form["description"] = tx.get("description", "")
                    update_existing_transaction(row_index, sync_form)
                return redirect(url_for("transactions.transaction_detail", row_index=row_index))
            warning = result.get("error", "The receipt was not saved.")

        elif action == "delete":
            result = delete_existing_transaction(row_index, confirm_settled_edit=request.form.get("confirm_settled_edit") == "1")
            if result.get("ok"):
                scoped_account_id = request.args.get("account_id") or request.form.get("account_id") or ""
                return redirect(url_for("transactions.transactions_page", account_id=scoped_account_id) if scoped_account_id else url_for("transactions.transactions_page"))
            warning = result.get("error", "The transaction was not deleted.")
        
        elif action == "delay":
            result = delay_existing_transaction(row_index, request.form.get("delay_date", ""))
            if result.get("ok"):
                return redirect(request.referrer or url_for("transactions.transactions_page"))
            warning = result.get("error", "The transaction date was not changed.")

        elif action == "update":
            result = update_existing_transaction(row_index, request.form)
            if result.get("ok"):
                return redirect(url_for("transactions.transaction_detail", row_index=row_index))
            warning = result.get("error", "The transaction was not updated.")

    try:
        tx, categories = transaction_detail_context(row_index)
    except LookupError:
        return f"Transaction {row_index} not found", 404

    payment_context = _safe_payment_form_context(tx)
    return render_template(
        "core/transaction_detail.html",
        tx=tx,
        categories=categories,
        **payment_context,
        transaction_warning=warning or request.args.get("warning", ""),
    )


def _safe_payment_form_context(tx: dict) -> dict:
    try:
        return payment_form_context(
            transaction_type=str(tx.get("type") or "expense"),
            selected_account_id=tx.get("account_id") or tx.get("account_key") or tx.get("account"),
            selected_payment_method_id=tx.get("payment_channel_method_id_snapshot") or tx.get("payment_method_id"),
        )
    except Exception:
        current_app.logger.exception("Failed to build payment form context for transaction detail")
        return {
            "payment_form": {
                "account_options": [],
                "payment_method_options": [],
                "selected_account_id": tx.get("account_id", ""),
                "selected_payment_method_id": tx.get("payment_method_id", ""),
                "selected_payment_method_explanation": "Payment options unavailable; existing transaction values are preserved.",
            },
            "payment_form_json": "{}",
        }


def _fallback_receipt_from_transaction(tx: dict) -> dict:
    amount = str(tx.get("amount") or "0.00")
    label = str(tx.get("sub_category") or tx.get("category") or tx.get("description") or "Item 001")
    return {
        "merchant": str(tx.get("description") or tx.get("category") or "Receipt"),
        "purchased_at": str(tx.get("created_at") or tx.get("date") or ""),
        "card_label": str(tx.get("payment_method_name_snapshot") or tx.get("payment_method") or ""),
        "card_last4": "",
        "card_network": "",
        "account_label": str(tx.get("account_name_snapshot") or tx.get("account_label") or tx.get("account") or ""),
        "items": [{"name": label, "qty": 1, "qty_display": "1", "unit_price": amount, "unit_price_display": amount, "line_total": amount, "line_total_display": amount}],
        "subtotal_display": amount,
        "discount_label": "No discount",
        "discount_amount": 0,
        "total_display": amount,
        "item_count": 1,
    }
