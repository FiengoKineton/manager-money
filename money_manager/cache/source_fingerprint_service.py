from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Iterable

from money_manager.config.app_home import load_app_version
from money_manager.config.user_paths import get_current_user_id, normalize_user_id
from money_manager.security.encryption_service import is_file_encrypted, read_envelope_metadata
from money_manager.storage.data_file_service import resolve_definition_path
from money_manager.storage.data_registry import all_definitions, definition_for_filename
from money_manager.cache import request_cache, runtime_epoch
from money_manager.cache.cache_keys import digest_payload
from money_manager.cache.cache_registry import CACHE_REGISTRY_VERSION

FINGERPRINT_PROCESS_TTL_SECONDS = float(os.environ.get("MONEY_MANAGER_FINGERPRINT_CACHE_TTL_SECONDS", "30") or 30)
_PATH_CACHE_TTL_SECONDS = float(os.environ.get("MONEY_MANAGER_PATH_FINGERPRINT_CACHE_TTL_SECONDS", "120") or 120)
_FINGERPRINT_LOCK = threading.RLock()
_SOURCE_FINGERPRINT_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_PATH_FINGERPRINT_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def clear_fingerprint_caches(user_id: str | None = None) -> None:
    safe_id = normalize_user_id(user_id) if user_id else ""
    with _FINGERPRINT_LOCK:
        if not safe_id:
            _SOURCE_FINGERPRINT_CACHE.clear()
            _PATH_FINGERPRINT_CACHE.clear()
            return
        for key in list(_SOURCE_FINGERPRINT_CACHE):
            if f'"user_id":"{safe_id}"' in key or safe_id in key:
                _SOURCE_FINGERPRINT_CACHE.pop(key, None)
        for key in list(_PATH_FINGERPRINT_CACHE):
            if key.startswith(f"{safe_id}:"):
                _PATH_FINGERPRINT_CACHE.pop(key, None)


def _process_get(cache: dict[str, tuple[float, dict[str, Any]]], key: str, ttl: float) -> dict[str, Any] | None:
    now = time.time()
    with _FINGERPRINT_LOCK:
        item = cache.get(key)
        if not item:
            return None
        saved_at, payload = item
        if ttl > 0 and now - saved_at > ttl:
            cache.pop(key, None)
            return None
        return dict(payload)


def _process_set(cache: dict[str, tuple[float, dict[str, Any]]], key: str, value: dict[str, Any]) -> None:
    with _FINGERPRINT_LOCK:
        cache[key] = (time.time(), dict(value))
        if len(cache) > 2048:
            for old_key in list(cache.keys())[:256]:
                cache.pop(old_key, None)

SMALL_FILE_HASH_LIMIT = 256 * 1024
STRICT_CACHE_FINGERPRINT = os.environ.get("MONEY_MANAGER_STRICT_CACHE_FINGERPRINT", "").strip() == "1"


TAG_ALIASES: dict[str, tuple[str, ...]] = {
    "transactions": ("expenses", "incomes", "investments", "money_rows"),
    "ledger": ("account_ledger",),
    "accounts": ("accounts", "account_events"),
    "payment_methods": ("payment_methods",),
    "credit_settlements": ("credit_settlements",),
    "internal_transfers": ("internal_transfers",),
    "pending": ("pending",),
    "recurring": ("recurring",),
    "payables": ("payables",),
    "receivables": ("receivables",),
    "debts": ("debts", "debt_rules"),
    "debt_rules": ("debt_rules",),
    "parent_support": ("parent_support", "parent_support_rules"),
    "parent_support_rules": ("parent_support_rules",),
    "expense_projects": ("expense_projects", "expense_project_movements", "expense_project_planned_items"),
    "expense_project_movements": ("expense_project_movements",),
    "expense_project_planned_items": ("expense_project_planned_items",),
    "investments": ("investments", "investment_assets", "investment_market_cache"),
    "investment_assets": ("investment_assets",),
    "investment_market_cache": ("investment_market_cache",),
    "documents": ("documents", "documents_metadata"),
    "document_types": ("document_types",),
    "contacts": ("contacts",),
    "profile": ("profile",),
    "preferences": ("preferences",),
    "navigation": ("navigation",),
    "i18n": ("preferences",),
    "integrity": ("expenses", "incomes", "investments", "account_ledger", "accounts", "payment_methods"),
    "backup": ("profile", "preferences", "expenses", "incomes", "investments", "accounts", "payment_methods"),
    "schema": ("profile", "preferences", "accounts", "payment_methods", "expenses", "incomes", "investments"),
    "categories": ("categories",),
    "money_rows": ("expenses", "incomes", "investments", "pending", "recurring", "debts", "payables", "receivables", "parent_support", "expense_projects", "internal_transfers", "account_ledger", "credit_settlements"),
}


def source_fingerprint(dependencies: Iterable[str] | None = None, *, user_id: str | None = None, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    safe_id = normalize_user_id(user_id or get_current_user_id()) if (user_id or get_current_user_id()) else ""
    wanted = _expand_tags(dependencies or ())
    extra_payload = extra or {}
    epoch_value = runtime_epoch.epoch(safe_id, wanted)
    memo_base = {
        "user_id": safe_id,
        "dependencies": sorted(wanted),
        "extra": extra_payload,
        "registry_version": CACHE_REGISTRY_VERSION,
        "runtime_epoch": epoch_value,
    }
    memo_key = "source_fingerprint:" + digest_payload(memo_base)

    sentinel = object()
    memoized = request_cache.get(memo_key, sentinel)
    if memoized is not sentinel:
        return dict(memoized)

    process_memoized = _process_get(_SOURCE_FINGERPRINT_CACHE, memo_key, FINGERPRINT_PROCESS_TTL_SECONDS)
    if process_memoized is not None:
        request_cache.set(memo_key, dict(process_memoized))
        return dict(process_memoized)

    files: dict[str, dict[str, Any]] = {}

    for definition in all_definitions():
        if definition.scope != "user" or definition.file_type not in {"json", "csv", "directory", "binary_folder"}:
            continue
        definition_tags = set(definition.invalidation_tags or ()) | {definition.name, definition.relative_path}
        if wanted and not (definition_tags & wanted):
            continue
        try:
            path = resolve_definition_path(definition, user_id=safe_id) if safe_id else Path(definition.relative_path)
        except Exception:
            path = Path(definition.relative_path)
        files[definition.name] = _cached_path_fingerprint(path, schema_version=definition.schema_version, user_id=safe_id)

    if not files and not wanted:
        for definition in all_definitions("user"):
            try:
                path = resolve_definition_path(definition, user_id=safe_id) if safe_id else Path(definition.relative_path)
            except Exception:
                path = Path(definition.relative_path)
            files[definition.name] = _cached_path_fingerprint(path, schema_version=definition.schema_version, user_id=safe_id)

    app_version = load_app_version()
    payload = {
        "schema_version": 2,
        "cache_registry_version": CACHE_REGISTRY_VERSION,
        "app_version": str(app_version.get("version") or ""),
        "data_schema_current": app_version.get("data_schema_current"),
        "user_id": safe_id,
        "dependencies": sorted(wanted),
        "runtime_epoch": epoch_value,
        "files": files,
        "extra": extra_payload,
    }
    payload["digest"] = digest_payload(payload)
    request_cache.set(memo_key, dict(payload))
    _process_set(_SOURCE_FINGERPRINT_CACHE, memo_key, dict(payload))
    return payload


def fingerprint_hash(fingerprint: dict[str, Any]) -> str:
    return str(fingerprint.get("digest") or digest_payload(fingerprint))


def fingerprint_for_path(path: str | os.PathLike[str], *, user_id: str | None = None) -> dict[str, Any]:
    target = Path(path)
    safe_id = normalize_user_id(user_id or get_current_user_id()) if (user_id or get_current_user_id()) else ""
    try:
        stat = target.stat()
        stat_payload = {"mtime_ns": int(stat.st_mtime_ns), "size": int(stat.st_size)}
    except Exception:
        stat_payload = {"mtime_ns": 0, "size": 0}
    memo_key = "path_fingerprint:" + digest_payload({"user_id": safe_id, "path": str(target), **stat_payload})
    sentinel = object()
    memoized = request_cache.get(memo_key, sentinel)
    if memoized is not sentinel:
        return dict(memoized)
    definition = definition_for_filename(target.name) or definition_for_filename(str(target))
    schema_version = definition.schema_version if definition else 1
    payload = _cached_path_fingerprint(target, schema_version=schema_version, user_id=safe_id)
    request_cache.set(memo_key, dict(payload))
    return payload


def tags_for_path(path: str | os.PathLike[str], *, user_id: str | None = None) -> tuple[str, ...]:
    target = Path(path)
    relative = ""
    if user_id:
        try:
            from money_manager.config.install_paths import USERS_DIR

            relative = target.resolve().relative_to((USERS_DIR / normalize_user_id(user_id)).resolve()).as_posix()
        except Exception:
            relative = ""
    definition = definition_for_filename(relative or target.name) or definition_for_filename(str(path))
    if definition is None:
        return ("money_rows",)
    tags = set(definition.invalidation_tags or ()) | {definition.name}
    # Promote file-specific tags to broader cache tags.
    for broad, aliases in TAG_ALIASES.items():
        if definition.name in aliases or tags.intersection(aliases):
            tags.add(broad)
    return tuple(sorted(tags))


def _expand_tags(tags: Iterable[str]) -> set[str]:
    expanded: set[str] = set()
    for tag in tags:
        tag_text = str(tag or "").strip()
        if not tag_text:
            continue
        expanded.add(tag_text)
        expanded.update(TAG_ALIASES.get(tag_text, ()))
    return expanded


def _cached_path_fingerprint(path: Path, *, schema_version: int = 1, user_id: str = "") -> dict[str, Any]:
    try:
        stat = path.stat()
        stat_payload = {"mtime_ns": int(stat.st_mtime_ns), "size": int(stat.st_size), "exists": True}
    except Exception:
        stat_payload = {"mtime_ns": 0, "size": 0, "exists": False}
    key = f"{normalize_user_id(user_id) if user_id else ''}:{path}:{schema_version}:{stat_payload['mtime_ns']}:{stat_payload['size']}:{stat_payload['exists']}"
    memoized = _process_get(_PATH_FINGERPRINT_CACHE, key, _PATH_CACHE_TTL_SECONDS)
    if memoized is not None:
        return memoized
    payload = _path_fingerprint(path, schema_version=schema_version)
    _process_set(_PATH_FINGERPRINT_CACHE, key, payload)
    return payload

def _path_fingerprint(path: Path, *, schema_version: int = 1) -> dict[str, Any]:
    item: dict[str, Any] = {
        "path": str(path),
        "exists": False,
        "mtime_ns": 0,
        "size": 0,
        "schema_version": schema_version,
        "encrypted": False,
        "envelope_version": "",
        "sha256": "",
    }
    try:
        if not path.exists():
            return item
        if path.is_dir():
            item.update(_dir_fingerprint(path))
            item["schema_version"] = schema_version
            return item
        stat = path.stat()
        item.update({"exists": True, "mtime_ns": int(stat.st_mtime_ns), "size": int(stat.st_size)})
        # Fast mode uses mtime/size + explicit runtime epochs.  Reading hashes
        # and encrypted-envelope metadata for every dependent file made normal
        # navigation feel extremely slow on Windows/AV/OneDrive setups.  Enable
        # MONEY_MANAGER_STRICT_CACHE_FINGERPRINT=1 for forensic/debug runs.
        if STRICT_CACHE_FINGERPRINT:
            item["encrypted"] = bool(is_file_encrypted(path))
            if item["encrypted"]:
                metadata = read_envelope_metadata(path)
                item["envelope_version"] = str(metadata.get("schema_version") or "")
                item["envelope_algorithm"] = str(metadata.get("algorithm") or "")
            if stat.st_size <= SMALL_FILE_HASH_LIMIT:
                item["sha256"] = _sha256_file(path)
    except Exception as exc:
        item["error"] = str(exc)[:160]
    return item


def _dir_fingerprint(path: Path) -> dict[str, Any]:
    exists = path.exists()
    files = []
    total_size = 0
    latest_mtime = 0
    if exists:
        for child in sorted(p for p in path.rglob("*") if p.is_file()):
            try:
                stat = child.stat()
                rel = child.relative_to(path).as_posix()
                total_size += int(stat.st_size)
                latest_mtime = max(latest_mtime, int(stat.st_mtime_ns))
                item = {"path": rel, "mtime_ns": int(stat.st_mtime_ns), "size": int(stat.st_size)}
                if STRICT_CACHE_FINGERPRINT:
                    item["encrypted"] = bool(is_file_encrypted(child))
                files.append(item)
            except Exception:
                continue
    digest = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return {"exists": exists, "mtime_ns": latest_mtime, "size": total_size, "directory_entries": len(files), "sha256": digest}


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 64), b""):
            h.update(chunk)
    return h.hexdigest()
