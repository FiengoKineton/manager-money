from __future__ import annotations

"""Adaptive rendered-page cache and background navigation warmer.

The calculation cache keeps expensive dataframes and summaries hot, but a normal
Flask navigation still has to execute the route, build the template context, and
render the complete HTML document.  This module adds a second, process-local
layer for safe authenticated GET pages:

* the current page is rendered normally and stored in memory;
* the browser asks for an adaptive warm-up plan after first paint;
* likely next pages are rendered one at a time in the background;
* a real click can then return the already-rendered HTML immediately;
* data writes invalidate only pages whose declared dependencies intersect the
  changed tags.

Rendered HTML never goes to disk or browser storage.  It is user-scoped, bounded
by an LRU limit, protected by the same data-version signatures as the hot
calculation cache, and sent with ``Cache-Control: no-store``.
"""

import json
import math
import os
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Iterable
from urllib.parse import urlencode

from flask import Response, g, jsonify, make_response, request, session, url_for

from money_manager.cache.cache_stats_service import user_cache_root
from money_manager.config.user_paths import get_current_user_id, normalize_user_id
from money_manager.performance import turbo_version_service

_ENABLED = os.environ.get("MONEY_MANAGER_ADAPTIVE_PAGE_CACHE", "1").strip() != "0"
_MAX_ENTRIES = max(8, int(os.environ.get("MONEY_MANAGER_PAGE_CACHE_ENTRIES", "64") or 64))
_MAX_TOTAL_BYTES = max(4 * 1024 * 1024, int(os.environ.get("MONEY_MANAGER_PAGE_CACHE_BYTES", str(48 * 1024 * 1024)) or (48 * 1024 * 1024)))
_MAX_ENTRY_BYTES = max(256 * 1024, int(os.environ.get("MONEY_MANAGER_PAGE_CACHE_ENTRY_BYTES", str(4 * 1024 * 1024)) or (4 * 1024 * 1024)))
_TTL_SECONDS = max(30.0, float(os.environ.get("MONEY_MANAGER_PAGE_CACHE_TTL_SECONDS", "600") or 600))
_WAIT_FOR_WARM_SECONDS = max(0.0, float(os.environ.get("MONEY_MANAGER_PAGE_CACHE_WAIT_SECONDS", "0.45") or 0.45))
_PLAN_LIMIT = max(1, int(os.environ.get("MONEY_MANAGER_BACKGROUND_WARM_LIMIT", "8") or 8))
_USAGE_FLUSH_SECONDS = max(1.0, float(os.environ.get("MONEY_MANAGER_NAV_USAGE_FLUSH_SECONDS", "4") or 4))
_VALIDATION_INTERVAL_SECONDS = max(0.0, float(os.environ.get("MONEY_MANAGER_PAGE_CACHE_VALIDATION_SECONDS", "2.0") or 2.0))
_PROCESS_TOKEN = uuid.uuid4().hex[:12]
_SCHEMA_TOKEN = "adaptive-page-cache-v2"

_SHELL_DEPENDENCIES = ("profile", "preferences", "navigation", "accounts")


@dataclass(frozen=True)
class PageDefinition:
    endpoint: str
    default_priority: int
    dependencies: tuple[str, ...]
    preserve_account_scope: bool = False


def _page(
    endpoint: str,
    priority: int,
    dependencies: Iterable[str],
    *,
    preserve_account_scope: bool = False,
) -> PageDefinition:
    requested = tuple(_SHELL_DEPENDENCIES) + tuple(str(item) for item in dependencies if str(item).strip())
    combined = tuple(sorted(set(turbo_version_service.expanded_tags(requested))))
    return PageDefinition(
        endpoint=endpoint,
        default_priority=int(priority),
        dependencies=combined,
        preserve_account_scope=bool(preserve_account_scope),
    )


# Defaults are intentionally practical rather than alphabetical.  The usage
# score gradually overtakes this order as the user visits different pages.
_PAGE_DEFINITIONS: tuple[PageDefinition, ...] = (
    _page("dashboard.index", 100, ("transactions", "ledger", "payment_methods", "pending", "recurring", "debts", "investments", "internal_transfers", "categories"), preserve_account_scope=True),
    _page("accounts.account_detail", 98, ("transactions", "ledger", "payment_methods", "internal_transfers", "credit_settlements", "pending", "account_reconciliation")),
    _page("accounts.accounts_page", 96, ("transactions", "ledger", "payment_methods", "internal_transfers", "credit_settlements", "pending")),
    _page("transactions.transactions_page", 94, ("transactions", "payment_methods", "categories", "internal_transfers", "credit_settlements"), preserve_account_scope=True),
    _page("financial_calendar.calendar_page", 88, ("transactions", "pending", "recurring", "payables", "receivables", "debts", "payment_methods", "notification_state")),
    _page("pending.pending_page", 82, ("pending", "recurring", "transactions", "payment_methods", "notification_state")),
    _page("analysis.analysis", 80, ("transactions", "ledger", "payment_methods", "pending", "recurring", "debts", "payables", "receivables", "investments", "internal_transfers", "categories"), preserve_account_scope=True),
    _page("dashboard.overview", 76, ("transactions", "ledger", "payment_methods", "pending", "recurring", "debts", "investments", "internal_transfers"), preserve_account_scope=True),
    _page("dashboard.overview_detailed", 74, ("transactions", "ledger", "payment_methods", "pending", "recurring", "debts", "investments", "internal_transfers"), preserve_account_scope=True),
    _page("yearly_summary.yearly_summary_page", 72, ("transactions", "ledger", "pending", "recurring", "debts", "payables", "receivables", "internal_transfers", "investments")),
    _page("pending.recurring_page", 68, ("recurring", "pending", "transactions", "payment_methods", "notification_state")),
    _page("investments.investments_page", 64, ("investments", "investment_assets", "investment_market_cache", "transactions")),
    _page("forecast.forecast", 60, ("transactions", "pending", "recurring", "payables", "receivables", "debts", "notification_state")),
    _page("internal_transfers.internal_transfers_page", 58, ("internal_transfers", "ledger", "transactions", "payment_methods")),
    _page("managed_recurring.bills_page", 56, ("recurring", "pending", "transactions", "payment_methods", "notification_state")),
    _page("managed_recurring.work_income_page", 54, ("recurring", "pending", "transactions", "payment_methods", "notification_state")),
    _page("payables.payables_page", 52, ("payables", "transactions", "contacts", "pending", "notification_state")),
    _page("debts.debts_page", 50, ("debts", "debt_rules", "transactions", "contacts", "pending", "notification_state")),
    _page("receivables.receivables_page", 48, ("receivables", "transactions", "contacts", "notification_state")),
    _page("planned_expenses.planned_expenses_page", 46, ("pending", "recurring", "transactions")),
    _page("savings_goals.savings_goals_page", 44, ("transactions", "accounts", "investments")),
    _page("expense_projects.expense_projects_page", 42, ("expense_projects", "expense_project_movements", "expense_project_planned_items", "transactions")),
    _page("currencies.currencies_page", 40, ("currencies", "transactions", "accounts")),
    _page("contacts.contacts_page", 38, ("contacts", "payables", "receivables", "debts")),
    _page("bonifico.bonifico_page", 36, ("contacts", "transactions", "accounts", "payment_methods", "ledger")),
    _page("documents.documents", 34, ("documents", "document_types")),
    _page("reconciliation.reconciliation_page", 32, ("transactions", "ledger", "accounts", "payment_methods", "account_reconciliation")),
    _page("automation.automation_page", 30, ("recurring", "pending", "categories", "transactions")),
    _page("mortgages.mortgages_page", 28, ("debts", "debt_rules", "pending", "transactions")),
    _page("discount_balances.discount_balances_page", 26, ("discount_balances", "transactions")),
    _page("parent_support.parent_support_page", 24, ("parent_support", "parent_support_rules", "transactions", "contacts")),
    _page("sparagnat.sparagnat_page", 22, ("sparagnat", "transactions")),
    _page("notifications.center", 20, ("notification_state", "pending", "recurring", "payables", "receivables", "debts")),
)
_DEFINITION_BY_ENDPOINT = {definition.endpoint: definition for definition in _PAGE_DEFINITIONS}

_VOLATILE_QUERY_KEYS = {
    "saved",
    "error",
    "warning",
    "message",
    "quick_message",
    "category_added",
    "next",
    "token",
    "download",
    "export_id",
}


@dataclass
class _PageEntry:
    key: str
    user_id: str
    endpoint: str
    path: str
    dependencies: tuple[str, ...]
    signature_digest: str
    status_code: int
    headers: dict[str, str]
    body: bytes
    created_at: float
    expires_at: float
    validated_at: float
    hits: int = 0


_LOCK = threading.RLock()
_ENTRIES: "OrderedDict[str, _PageEntry]" = OrderedDict()
_TOTAL_BYTES = 0
_INFLIGHT: dict[str, threading.Event] = {}
_ENDPOINT_REVISIONS: dict[tuple[str, str], int] = {}
_STATS = {
    "hits": 0,
    "misses": 0,
    "stores": 0,
    "invalidations": 0,
    "warm_requests": 0,
    "warm_skips": 0,
    "singleflight_waits": 0,
}
_USAGE: dict[str, dict[str, Any]] = {}
_USAGE_LOADED: set[str] = set()
_USAGE_TIMERS: dict[str, threading.Timer] = {}


def init_app(app) -> None:
    """Register request hooks and the adaptive navigation-plan endpoint."""
    if not _ENABLED:
        return

    @app.get("/api/performance/navigation-plan", endpoint="money_manager_navigation_plan")
    def _navigation_plan_api():
        user_id = _current_user_id()
        if not user_id:
            return jsonify({"ok": False, "items": []}), 401
        current_endpoint = str(request.args.get("current") or "").strip()
        account_id = str(request.args.get("account_id") or "").strip()
        items = navigation_plan(
            app,
            user_id=user_id,
            current_endpoint=current_endpoint,
            account_id=account_id,
        )
        response = jsonify({
            "ok": True,
            "process": _PROCESS_TOKEN,
            "current": current_endpoint,
            "items": items,
        })
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.before_request
    def _adaptive_page_cache_before_request():
        return before_request()

    @app.after_request
    def _adaptive_page_cache_after_request(response):
        return after_request(response)

    @app.teardown_request
    def _adaptive_page_cache_teardown(error=None):
        release_inflight_if_owned()


def is_warmup_request() -> bool:
    try:
        return request.headers.get("X-MoneyManager-Warmup", "").strip() == "1"
    except Exception:
        return False


def before_request():
    if not _ENABLED or not _request_is_cacheable():
        return None

    user_id = _current_user_id()
    if not user_id:
        return None

    endpoint = str(request.endpoint or "")
    definition = _DEFINITION_BY_ENDPOINT.get(endpoint)
    if definition is None:
        return None

    warmup = is_warmup_request()
    if not warmup:
        record_visit(user_id, endpoint)

    # Never reuse a document that is supposed to consume transient session
    # state.  The project currently does not use Flask flash messages heavily,
    # but this guard keeps the cache correct if one is added later.
    if session.get("_flashes"):
        setattr(g, "_money_manager_page_cache_blocked", True)
        return None

    key = _request_cache_key(user_id, endpoint)
    setattr(g, "_money_manager_page_cache_key", key)
    setattr(g, "_money_manager_page_cache_user", user_id)
    setattr(g, "_money_manager_page_cache_definition", definition)
    setattr(g, "_money_manager_page_cache_warmup", warmup)

    entry = _get_valid_entry(key, user_id, definition)
    if entry is not None:
        setattr(g, "_money_manager_page_cache_hit", True)
        if warmup:
            _increment_stat("warm_skips")
            response = make_response("", 204)
            response.headers["X-MoneyManager-Warmup"] = "already-hot"
            response.headers["Cache-Control"] = "no-store"
            return response
        return _response_from_entry(entry)

    _increment_stat("misses")
    if warmup:
        _increment_stat("warm_requests")

    existing_event: threading.Event | None = None
    with _LOCK:
        existing_event = _INFLIGHT.get(key)
        if existing_event is None:
            existing_event = threading.Event()
            _INFLIGHT[key] = existing_event
            setattr(g, "_money_manager_page_cache_owner", True)

    if getattr(g, "_money_manager_page_cache_owner", False):
        return None

    # A warm request must never duplicate work already in progress.  A real click
    # waits briefly for the background builder and then consumes its result.
    if warmup:
        _increment_stat("warm_skips")
        response = make_response("", 202)
        response.headers["X-MoneyManager-Warmup"] = "in-progress"
        response.headers["Cache-Control"] = "no-store"
        return response

    _increment_stat("singleflight_waits")
    existing_event.wait(timeout=_WAIT_FOR_WARM_SECONDS)
    entry = _get_valid_entry(key, user_id, definition)
    if entry is not None:
        setattr(g, "_money_manager_page_cache_hit", True)
        return _response_from_entry(entry)
    return None


def after_request(response):
    if not _ENABLED:
        return response

    key = getattr(g, "_money_manager_page_cache_key", "")
    definition = getattr(g, "_money_manager_page_cache_definition", None)
    user_id = getattr(g, "_money_manager_page_cache_user", "")
    warmup = bool(getattr(g, "_money_manager_page_cache_warmup", False))
    cache_hit = bool(getattr(g, "_money_manager_page_cache_hit", False))

    try:
        session_changed = bool(getattr(session, "modified", False))
        cache_blocked = bool(getattr(g, "_money_manager_page_cache_blocked", False))
        if key and definition is not None and user_id and not cache_hit and not session_changed and not cache_blocked and _response_is_cacheable(response):
            _store_response(key, user_id, definition, response)
            if warmup:
                warmed = make_response("", 204)
                warmed.headers["X-MoneyManager-Warmup"] = "stored"
                warmed.headers["X-MoneyManager-Page-Cache"] = "WARM"
                warmed.headers["Cache-Control"] = "no-store"
                response = warmed
    finally:
        release_inflight_if_owned()

    try:
        if response.mimetype == "text/html":
            response.headers["Cache-Control"] = "no-store, private"
    except Exception:
        pass
    return response


def release_inflight_if_owned() -> None:
    if not bool(getattr(g, "_money_manager_page_cache_owner", False)):
        return
    key = str(getattr(g, "_money_manager_page_cache_key", "") or "")
    if not key:
        return
    with _LOCK:
        event = _INFLIGHT.pop(key, None)
    if event is not None:
        event.set()
    setattr(g, "_money_manager_page_cache_owner", False)


def invalidate_pages(*, user_id: str | None = None, tags: Iterable[str] | None = None) -> int:
    """Invalidate only rendered pages affected by the changed data tags."""
    safe_id = normalize_user_id(user_id or get_current_user_id()) if (user_id or get_current_user_id()) else ""
    if not safe_id:
        return 0
    wanted = set(turbo_version_service.expanded_tags(tags or ()))
    removed = 0
    global _TOTAL_BYTES
    with _LOCK:
        for definition in _PAGE_DEFINITIONS:
            if not wanted or set(definition.dependencies).intersection(wanted):
                revision_key = (safe_id, definition.endpoint)
                _ENDPOINT_REVISIONS[revision_key] = int(_ENDPOINT_REVISIONS.get(revision_key, 0)) + 1
        for key, entry in list(_ENTRIES.items()):
            if entry.user_id != safe_id:
                continue
            if wanted and not set(entry.dependencies).intersection(wanted):
                continue
            _ENTRIES.pop(key, None)
            _TOTAL_BYTES = max(0, _TOTAL_BYTES - len(entry.body))
            removed += 1
        if removed:
            _STATS["invalidations"] = int(_STATS.get("invalidations", 0)) + removed
    return removed


def clear_all_pages(*, user_id: str | None = None) -> int:
    return invalidate_pages(user_id=user_id, tags=())


def navigation_plan(app, *, user_id: str, current_endpoint: str = "", account_id: str = "") -> list[dict[str, Any]]:
    safe_id = normalize_user_id(user_id)
    usage = _usage_for_user(safe_id)
    now = time.time()
    candidates: list[tuple[float, PageDefinition, str]] = []
    preferred_account_id = _preferred_account_id(safe_id, account_id)

    for definition in _PAGE_DEFINITIONS:
        if definition.endpoint == current_endpoint or definition.endpoint not in app.view_functions:
            continue
        kwargs: dict[str, Any] = {}
        if definition.endpoint == "accounts.account_detail":
            if not preferred_account_id:
                continue
            kwargs["account_key"] = preferred_account_id
        elif account_id and definition.preserve_account_scope:
            kwargs["account_id"] = account_id
        try:
            url = url_for(definition.endpoint, **kwargs)
        except Exception:
            continue
        score = _adaptive_score(definition, usage.get(definition.endpoint) or {}, now)
        candidates.append((score, definition, url))

    candidates.sort(key=lambda item: (-item[0], -item[1].default_priority, item[1].endpoint))
    result: list[dict[str, Any]] = []
    with _LOCK:
        for score, definition, url in candidates[:_PLAN_LIMIT]:
            revision = int(_ENDPOINT_REVISIONS.get((safe_id, definition.endpoint), 0))
            result.append({
                "endpoint": definition.endpoint,
                "url": url,
                "priority": round(score, 3),
                "token": f"{_PROCESS_TOKEN}:{revision}",
            })
    return result


def _preferred_account_id(user_id: str, explicit_account_id: str = "") -> str:
    candidate = str(explicit_account_id or "").strip()
    if not candidate:
        try:
            from money_manager.services.profile_service import load_profile

            profile = load_profile(user_id=user_id)
            candidate = str(
                profile.get("default_current_account_id")
                or profile.get("default_main_account")
                or "main_bank"
            ).strip()
        except Exception:
            candidate = "main_bank"
    try:
        from money_manager.services.account_config_service import configured_account_key

        return str(configured_account_key(candidate, user_id=user_id) or "")
    except Exception:
        return candidate


def record_visit(user_id: str, endpoint: str) -> None:
    if endpoint not in _DEFINITION_BY_ENDPOINT:
        return
    safe_id = normalize_user_id(user_id)
    usage = _usage_for_user(safe_id)
    now = time.time()
    with _LOCK:
        row = dict(usage.get(endpoint) or {})
        last_seen = float(row.get("last_seen") or 0.0)
        recent = float(row.get("recent") or 0.0)
        # Seven-day half-life: recent habits adapt quickly without forgetting the
        # user's normal workflow after a quiet week.
        if last_seen > 0:
            recent *= math.pow(0.5, max(0.0, now - last_seen) / (7.0 * 86400.0))
        row["count"] = int(row.get("count") or 0) + 1
        row["recent"] = recent + 1.0
        row["last_seen"] = now
        usage[endpoint] = row
        _USAGE[safe_id] = usage
    _schedule_usage_flush(safe_id)


def stats(user_id: str | None = None) -> dict[str, Any]:
    safe_id = normalize_user_id(user_id or get_current_user_id()) if (user_id or get_current_user_id()) else ""
    now = time.time()
    with _LOCK:
        entries = [entry for entry in _ENTRIES.values() if not safe_id or entry.user_id == safe_id]
        usage = dict(_USAGE.get(safe_id) or {}) if safe_id else {}
        return {
            "enabled": _ENABLED,
            "entry_count": len(entries),
            "total_bytes": sum(len(entry.body) for entry in entries),
            "max_entries": _MAX_ENTRIES,
            "ttl_seconds": _TTL_SECONDS,
            "stats": dict(_STATS),
            "entries": [
                {
                    "endpoint": entry.endpoint,
                    "path": entry.path,
                    "age_seconds": round(now - entry.created_at, 3),
                    "expires_in_seconds": round(entry.expires_at - now, 3),
                    "hits": entry.hits,
                    "bytes": len(entry.body),
                }
                for entry in entries
            ],
            "usage": usage,
        }


def _request_is_cacheable() -> bool:
    try:
        if request.method != "GET":
            return False
        endpoint = str(request.endpoint or "")
        if endpoint not in _DEFINITION_BY_ENDPOINT:
            return False
        if request.headers.get("X-MoneyManager-No-Page-Cache", "").strip() == "1":
            return False
        accept = str(request.headers.get("Accept") or "")
        if accept and "text/html" not in accept and "*/*" not in accept:
            return False
        if any(key in request.args for key in _VOLATILE_QUERY_KEYS):
            return False
        return True
    except Exception:
        return False


def _response_is_cacheable(response) -> bool:
    try:
        if int(response.status_code) != 200:
            return False
        if response.mimetype != "text/html":
            return False
        if response.is_streamed or response.direct_passthrough:
            return False
        if response.headers.get("Set-Cookie"):
            return False
        body = response.get_data()
        return bool(body) and len(body) <= _MAX_ENTRY_BYTES
    except Exception:
        return False


def _current_user_id() -> str:
    resolved = get_current_user_id()
    return normalize_user_id(resolved) if resolved else ""


def _request_cache_key(user_id: str, endpoint: str) -> str:
    pairs = sorted((str(key), str(value)) for key, values in request.args.lists() for value in values)
    query = urlencode(pairs, doseq=True)
    path = request.path + (f"?{query}" if query else "")
    return f"{_SCHEMA_TOKEN}|{user_id}|{endpoint}|{path}"


def _entry_signature(definition: PageDefinition, user_id: str) -> str:
    payload = turbo_version_service.signature(
        definition.dependencies,
        user_id=user_id,
        extra={"page_cache_schema": _SCHEMA_TOKEN},
    )
    return str(payload.get("digest") or "")


def _get_valid_entry(key: str, user_id: str, definition: PageDefinition) -> _PageEntry | None:
    now = time.time()
    with _LOCK:
        entry = _ENTRIES.get(key)
        if entry is None:
            return None
        if entry.expires_at <= now:
            _remove_entry_locked(key)
            return None
        # Consecutive navigation requests often arrive within milliseconds (the
        # document plus topbar/lazy helpers).  Recomputing even the throttled
        # dependency signature for every hit adds avoidable lock and stat work.
        # The underlying external-file poll is already delayed, so a short
        # validation grace preserves correctness while keeping the hot path hot.
        if now - float(entry.validated_at or 0.0) <= _VALIDATION_INTERVAL_SECONDS:
            entry.hits += 1
            _ENTRIES.move_to_end(key)
            _STATS["hits"] = int(_STATS.get("hits", 0)) + 1
            return entry

    try:
        digest = _entry_signature(definition, user_id)
    except Exception:
        digest = ""
    if not digest or digest != entry.signature_digest:
        with _LOCK:
            _remove_entry_locked(key)
        return None

    with _LOCK:
        current = _ENTRIES.get(key)
        if current is None:
            return None
        current.validated_at = now
        current.hits += 1
        _ENTRIES.move_to_end(key)
        _STATS["hits"] = int(_STATS.get("hits", 0)) + 1
        return current


def _store_response(key: str, user_id: str, definition: PageDefinition, response) -> None:
    global _TOTAL_BYTES
    try:
        body = bytes(response.get_data())
        digest = _entry_signature(definition, user_id)
    except Exception:
        return
    if not body or not digest or len(body) > _MAX_ENTRY_BYTES:
        return

    headers: dict[str, str] = {}
    for name in ("Content-Type", "Content-Language"):
        value = response.headers.get(name)
        if value:
            headers[name] = str(value)
    now = time.time()
    entry = _PageEntry(
        key=key,
        user_id=user_id,
        endpoint=definition.endpoint,
        path=request.full_path.rstrip("?"),
        dependencies=definition.dependencies,
        signature_digest=digest,
        status_code=int(response.status_code),
        headers=headers,
        body=body,
        created_at=now,
        expires_at=now + _TTL_SECONDS,
        validated_at=now,
    )
    with _LOCK:
        old = _ENTRIES.pop(key, None)
        if old is not None:
            _TOTAL_BYTES = max(0, _TOTAL_BYTES - len(old.body))
        _ENTRIES[key] = entry
        _TOTAL_BYTES += len(body)
        _STATS["stores"] = int(_STATS.get("stores", 0)) + 1
        _evict_locked()


def _response_from_entry(entry: _PageEntry) -> Response:
    response = make_response(entry.body, entry.status_code)
    for name, value in entry.headers.items():
        response.headers[name] = value
    response.headers["X-MoneyManager-Page-Cache"] = "HIT"
    response.headers["X-MoneyManager-Page-Cache-Age"] = f"{max(0.0, time.time() - entry.created_at):.3f}"
    response.headers["Cache-Control"] = "no-store, private"
    return response


def _remove_entry_locked(key: str) -> None:
    global _TOTAL_BYTES
    entry = _ENTRIES.pop(key, None)
    if entry is not None:
        _TOTAL_BYTES = max(0, _TOTAL_BYTES - len(entry.body))


def _evict_locked() -> None:
    while len(_ENTRIES) > _MAX_ENTRIES or _TOTAL_BYTES > _MAX_TOTAL_BYTES:
        key, _entry = next(iter(_ENTRIES.items()))
        _remove_entry_locked(key)


def _increment_stat(name: str) -> None:
    with _LOCK:
        _STATS[name] = int(_STATS.get(name, 0)) + 1


def _adaptive_score(definition: PageDefinition, usage: dict[str, Any], now: float) -> float:
    count = max(0, int(usage.get("count") or 0))
    recent = max(0.0, float(usage.get("recent") or 0.0))
    last_seen = max(0.0, float(usage.get("last_seen") or 0.0))
    if last_seen > 0:
        recent *= math.pow(0.5, max(0.0, now - last_seen) / (7.0 * 86400.0))
    recency_bonus = 0.0
    if last_seen > 0:
        recency_bonus = max(0.0, 18.0 - (now - last_seen) / 3600.0)
    return float(definition.default_priority) + 9.0 * math.log1p(count) + 5.0 * recent + recency_bonus


def _usage_path(user_id: str) -> Path:
    return user_cache_root(user_id) / "navigation_usage.json"


def _usage_for_user(user_id: str) -> dict[str, Any]:
    safe_id = normalize_user_id(user_id)
    with _LOCK:
        if safe_id in _USAGE_LOADED:
            return _USAGE.setdefault(safe_id, {})
        _USAGE_LOADED.add(safe_id)
    path = _usage_path(safe_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        payload = {}
    pages = payload.get("pages") if isinstance(payload, dict) and isinstance(payload.get("pages"), dict) else {}
    clean: dict[str, Any] = {}
    for endpoint, row in pages.items():
        if endpoint not in _DEFINITION_BY_ENDPOINT or not isinstance(row, dict):
            continue
        clean[endpoint] = {
            "count": max(0, int(row.get("count") or 0)),
            "recent": max(0.0, float(row.get("recent") or 0.0)),
            "last_seen": max(0.0, float(row.get("last_seen") or 0.0)),
        }
    with _LOCK:
        _USAGE[safe_id] = clean
        return _USAGE[safe_id]


def _schedule_usage_flush(user_id: str) -> None:
    safe_id = normalize_user_id(user_id)

    def _flush() -> None:
        try:
            _flush_usage(safe_id)
        finally:
            with _LOCK:
                _USAGE_TIMERS.pop(safe_id, None)

    with _LOCK:
        timer = _USAGE_TIMERS.get(safe_id)
        if timer is not None:
            try:
                timer.cancel()
            except Exception:
                pass
        timer = threading.Timer(_USAGE_FLUSH_SECONDS, _flush)
        timer.daemon = True
        _USAGE_TIMERS[safe_id] = timer
        timer.start()


def _flush_usage(user_id: str) -> None:
    safe_id = normalize_user_id(user_id)
    with _LOCK:
        pages = json.loads(json.dumps(_USAGE.get(safe_id) or {}))
    path = _usage_path(safe_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": 1, "updated_at": time.time(), "pages": pages}
    try:
        with NamedTemporaryFile("w", delete=False, dir=str(path.parent), prefix=".navigation_usage.", suffix=".tmp", encoding="utf-8") as tmp:
            json.dump(payload, tmp, indent=2, ensure_ascii=False)
            temp_name = tmp.name
        Path(temp_name).replace(path)
    except Exception:
        try:
            Path(temp_name).unlink(missing_ok=True)  # type: ignore[name-defined]
        except Exception:
            pass
