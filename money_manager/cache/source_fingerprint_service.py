from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable

from money_manager.config.app_home import load_app_version
from money_manager.config.user_paths import get_current_user_id, normalize_user_id
from money_manager.security.encryption_service import is_file_encrypted, read_envelope_metadata
from money_manager.storage.data_file_service import resolve_definition_path
from money_manager.storage.data_registry import all_definitions, definition_for_filename
from money_manager.cache.cache_keys import digest_payload
from money_manager.cache.cache_registry import CACHE_REGISTRY_VERSION

SMALL_FILE_HASH_LIMIT = 256 * 1024

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
        files[definition.name] = _path_fingerprint(path, schema_version=definition.schema_version)

    if not files and not wanted:
        for definition in all_definitions("user"):
            try:
                path = resolve_definition_path(definition, user_id=safe_id) if safe_id else Path(definition.relative_path)
            except Exception:
                path = Path(definition.relative_path)
            files[definition.name] = _path_fingerprint(path, schema_version=definition.schema_version)

    app_version = load_app_version()
    payload = {
        "schema_version": 1,
        "cache_registry_version": CACHE_REGISTRY_VERSION,
        "app_version": str(app_version.get("version") or ""),
        "data_schema_current": app_version.get("data_schema_current"),
        "user_id": safe_id,
        "dependencies": sorted(wanted),
        "files": files,
        "extra": extra or {},
    }
    payload["digest"] = digest_payload(payload)
    return payload


def fingerprint_hash(fingerprint: dict[str, Any]) -> str:
    return str(fingerprint.get("digest") or digest_payload(fingerprint))


def fingerprint_for_path(path: str | os.PathLike[str], *, user_id: str | None = None) -> dict[str, Any]:
    definition = definition_for_filename(Path(path).name) or definition_for_filename(str(path))
    schema_version = definition.schema_version if definition else 1
    return _path_fingerprint(Path(path), schema_version=schema_version)


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
                files.append({"path": rel, "mtime_ns": int(stat.st_mtime_ns), "size": int(stat.st_size), "encrypted": bool(is_file_encrypted(child))})
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
