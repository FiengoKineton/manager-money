from __future__ import annotations

import copy
import json
import pickle
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from money_manager.cache.cache_keys import hashed_entry_id
from money_manager.cache.cache_stats_service import load_stats, user_cache_root
from money_manager.cache.cache_registry import CacheDefinition
from money_manager.config.user_paths import get_current_user_id, normalize_user_id
from money_manager.security.encryption_service import decrypt_bytes, encrypt_bytes, is_encrypted_bytes, is_file_encrypted
from money_manager.security.key_manager import is_encryption_enabled
from money_manager.security.session_vault import get_dek

CACHE_FORMAT_VERSION = 2


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def resolve_user_id(user_id: str | None = None) -> str:
    resolved = user_id or get_current_user_id()
    if not resolved:
        raise RuntimeError("No authenticated user available for cache storage.")
    return normalize_user_id(resolved)


def ensure_cache_dirs(user_id: str | None = None) -> Path:
    root = user_cache_root(user_id)
    for folder in ("computed", "tables", "plots", "locks", "tmp"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    index_path(root).touch(exist_ok=True)
    if not index_path(root).read_text(encoding="utf-8", errors="ignore").strip():
        write_index({"schema_version": 1, "entries": {}}, user_id=user_id)
    return root


def index_path(root: Path | None = None, user_id: str | None = None) -> Path:
    return (root or user_cache_root(user_id)) / "index.json"


def read_index(user_id: str | None = None) -> dict[str, Any]:
    root = ensure_cache_dirs(user_id)
    path = index_path(root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() and path.stat().st_size else {}
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    entries = payload.get("entries") if isinstance(payload.get("entries"), dict) else {}
    return {"schema_version": int(payload.get("schema_version") or 1), "entries": entries}


def write_index(index: dict[str, Any], user_id: str | None = None) -> None:
    root = user_cache_root(user_id)
    root.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": 1, "entries": dict((index or {}).get("entries") or {})}
    path = index_path(root)
    with NamedTemporaryFile("w", delete=False, dir=str(root), prefix=".index.", suffix=".tmp", encoding="utf-8") as tmp:
        json.dump(payload, tmp, indent=2, ensure_ascii=False)
        temp_name = tmp.name
    Path(temp_name).replace(path)


def read_entry(key: str, definition: CacheDefinition, source_fingerprint: dict[str, Any], *, user_id: str | None = None) -> tuple[bool, Any, str]:
    safe_id = resolve_user_id(user_id)
    entry_id = hashed_entry_id(key)
    index = read_index(safe_id)
    meta = index.get("entries", {}).get(entry_id)
    if not isinstance(meta, dict):
        return False, None, "miss"
    if meta.get("status") != "valid":
        return False, None, str(meta.get("status") or "stale")
    if meta.get("source_fingerprint") != source_fingerprint.get("digest"):
        meta["status"] = "stale"
        meta["stale_reason"] = "source_fingerprint_changed"
        index["entries"][entry_id] = meta
        write_index(index, safe_id)
        return False, None, "stale"
    expires_at = str(meta.get("expires_at") or "")
    if expires_at and _is_expired(expires_at):
        meta["status"] = "stale"
        meta["stale_reason"] = "ttl_expired"
        index["entries"][entry_id] = meta
        write_index(index, safe_id)
        return False, None, "expired"
    path = user_cache_root(safe_id) / str(meta.get("path") or "")
    if not path.exists() or not path.is_file():
        return False, None, "missing_file"
    try:
        raw = path.read_bytes()
        if bool(meta.get("encrypted")) or is_encrypted_bytes(raw):
            if not is_encryption_enabled(safe_id):
                return False, None, "encrypted_but_disabled"
            dek = get_dek(safe_id)
            if dek is None:
                return False, None, "vault_locked"
            raw = decrypt_bytes(raw, dek)
        record = pickle.loads(raw)
        if not isinstance(record, dict) or record.get("format") != CACHE_FORMAT_VERSION:
            return False, None, "format_mismatch"
        if record.get("key") != key:
            return False, None, "key_mismatch"
        return True, _safe_copy(record.get("value")), "hit"
    except Exception as exc:
        return False, None, f"error:{exc}"


def write_entry(key: str, value: Any, definition: CacheDefinition, source_fingerprint: dict[str, Any], *, user_id: str | None = None) -> dict[str, Any] | None:
    if not definition.disk_cache_allowed:
        return None
    safe_id = resolve_user_id(user_id)
    root = ensure_cache_dirs(safe_id)
    entry_id = hashed_entry_id(key)
    should_encrypt = bool(definition.sensitive and definition.encrypted and is_encryption_enabled(safe_id))
    encrypted = False
    suffix = ".mmcache" if should_encrypt else ".pkl"
    rel_path = Path("computed") / f"{entry_id}{suffix}"
    path = root / rel_path
    record = {"format": CACHE_FORMAT_VERSION, "key": key, "saved_at": time.time(), "value": value}
    try:
        raw = pickle.dumps(record, protocol=pickle.HIGHEST_PROTOCOL)
        if should_encrypt:
            dek = get_dek(safe_id)
            if dek is None:
                return None
            raw = encrypt_bytes(raw, dek, content_type="application/x-money-manager-cache", original_logical_name=f"cache/{definition.name}", original_filename=path.name)
            encrypted = True
        _atomic_write_bytes(path, raw)
        stat = path.stat()
        now = utc_now()
        expires_at = _expires_at(definition.ttl_seconds)
        meta = {
            "key": key,
            "name": definition.name,
            "version": definition.version,
            "path": rel_path.as_posix(),
            "created_at": now,
            "updated_at": now,
            "expires_at": expires_at,
            "source_fingerprint": source_fingerprint.get("digest", ""),
            "tags": list(definition.dependencies),
            "sensitive": bool(definition.sensitive),
            "encrypted": encrypted,
            "status": "valid",
            "size_bytes": int(stat.st_size),
        }
        index = read_index(safe_id)
        old = index["entries"].get(entry_id)
        if isinstance(old, dict) and old.get("created_at"):
            meta["created_at"] = old.get("created_at")
        index["entries"][entry_id] = meta
        write_index(index, safe_id)
        return meta
    except Exception:
        return None


def mark_stale(entry_ids: list[str] | None = None, *, tags: set[str] | None = None, user_id: str | None = None, reason: str = "manual") -> int:
    safe_id = resolve_user_id(user_id)
    index = read_index(safe_id)
    entries = index.get("entries", {})
    count = 0
    wanted_ids = set(entry_ids or [])
    wanted_tags = set(tags or [])
    for entry_id, meta in list(entries.items()):
        if not isinstance(meta, dict):
            continue
        matches_id = not wanted_ids or entry_id in wanted_ids or str(meta.get("key")) in wanted_ids
        matches_tag = not wanted_tags or bool(set(meta.get("tags") or []) & wanted_tags)
        if matches_id and matches_tag and meta.get("status") != "stale":
            meta["status"] = "stale"
            meta["stale_reason"] = reason
            meta["updated_at"] = utc_now()
            entries[entry_id] = meta
            count += 1
    if count:
        index["entries"] = entries
        write_index(index, safe_id)
    return count


def cleanup_stale_entries(*, user_id: str | None = None) -> int:
    safe_id = resolve_user_id(user_id)
    root = user_cache_root(safe_id)
    index = read_index(safe_id)
    entries = index.get("entries", {})
    removed = 0
    for entry_id, meta in list(entries.items()):
        if not isinstance(meta, dict):
            entries.pop(entry_id, None)
            continue
        if meta.get("status") != "stale":
            continue
        path = root / str(meta.get("path") or "")
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass
        entries.pop(entry_id, None)
        removed += 1
    index["entries"] = entries
    write_index(index, safe_id)
    return removed


def clear_user_cache(*, user_id: str | None = None) -> int:
    safe_id = resolve_user_id(user_id)
    root = user_cache_root(safe_id)
    removed = 0
    for folder in ("computed", "tables", "plots", "locks", "tmp"):
        target = root / folder
        if not target.exists():
            continue
        for child in list(target.rglob("*")):
            if child.is_file():
                try:
                    child.unlink()
                    removed += 1
                except OSError:
                    pass
        for child in sorted([p for p in target.rglob("*") if p.is_dir()], reverse=True):
            try:
                child.rmdir()
            except OSError:
                pass
    write_index({"schema_version": 1, "entries": {}}, safe_id)
    return removed


def cache_inventory(*, user_id: str | None = None) -> dict[str, Any]:
    safe_id = normalize_user_id(user_id or get_current_user_id()) if (user_id or get_current_user_id()) else ""
    root = user_cache_root(safe_id) if safe_id else user_cache_root("anonymous")
    index = read_index(safe_id) if safe_id else {"entries": {}}
    entries = [dict(value, id=key) for key, value in sorted(index.get("entries", {}).items()) if isinstance(value, dict)]
    size = 0
    files = 0
    for path in root.rglob("*"):
        if path.is_file():
            files += 1
            try:
                size += path.stat().st_size
            except OSError:
                pass
    stale = [entry for entry in entries if entry.get("status") != "valid"]
    encrypted_sensitive = sum(1 for entry in entries if entry.get("sensitive") and entry.get("encrypted"))
    plaintext_sensitive = sum(1 for entry in entries if entry.get("sensitive") and not entry.get("encrypted"))
    stats = load_stats(safe_id) if safe_id else load_stats("anonymous")
    hits = int(stats.get("hits", 0) or 0)
    misses = int(stats.get("misses", 0) or 0)
    hit_rate = 0.0 if hits + misses == 0 else hits / (hits + misses) * 100
    return {
        "user_id": safe_id,
        "location": str(root),
        "entry_count": len(entries),
        "file_count": files,
        "size_bytes": size,
        "size_label": _size_label(size),
        "stale_count": len(stale),
        "entries": entries,
        "stale_entries": stale,
        "encrypted_sensitive_count": encrypted_sensitive,
        "plaintext_sensitive_count": plaintext_sensitive,
        "sensitive_cache_encrypted": plaintext_sensitive == 0,
        "stats": {**stats, "hit_rate": hit_rate, "hit_rate_label": f"{hit_rate:.1f}%"},
    }


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("wb", delete=False, dir=str(path.parent), prefix=f".{path.stem}.", suffix=".tmp") as tmp:
        tmp.write(payload)
        temp_name = tmp.name
    Path(temp_name).replace(path)


def _safe_copy(value: Any) -> Any:
    try:
        return copy.deepcopy(value)
    except Exception:
        return value


def _expires_at(ttl_seconds: int | None) -> str:
    if not ttl_seconds:
        return ""
    return datetime.fromtimestamp(time.time() + int(ttl_seconds), timezone.utc).isoformat(timespec="seconds")


def _is_expired(value: str) -> bool:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() < time.time()
    except Exception:
        return False


def _size_label(size: int) -> str:
    amount = float(size or 0)
    for unit in ["B", "KB", "MB", "GB"]:
        if amount < 1024 or unit == "GB":
            return f"{amount:.1f} {unit}" if unit != "B" else f"{int(amount)} B"
        amount /= 1024
