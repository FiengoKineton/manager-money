from __future__ import annotations

"""Low-latency data-version signatures for turbo mode.

The older cache fingerprint path was correct, but it still had to scan the data
registry and stat several files when a page first touched a calculation.  In a
local desktop Flask app that does all writes through the application, the fastest
correct invalidation signal is the runtime data version bumped by those writes.

This service keeps that hot-path version in memory and only polls the filesystem
occasionally to catch manual edits/imports done outside the web app.
"""

import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from money_manager.cache import runtime_epoch
from money_manager.cache.cache_keys import digest_payload
from money_manager.cache.source_fingerprint_service import TAG_ALIASES
from money_manager.config.app_home import load_app_version
from money_manager.config.user_paths import normalize_user_id
from money_manager.storage.data_file_service import resolve_definition_path
from money_manager.storage.data_registry import DataFileDefinition, all_definitions

# Runtime-version mode is the professional fast path for the desktop/web app.
# External file edits are still detected, but not on every request.
TRUST_RUNTIME_WRITES = os.environ.get("MONEY_MANAGER_TURBO_TRUST_RUNTIME_WRITES", "1").strip() != "0"
EXTERNAL_POLL_SECONDS = float(os.environ.get("MONEY_MANAGER_TURBO_EXTERNAL_POLL_SECONDS", "45") or 45)
MAX_SIGNATURES = int(os.environ.get("MONEY_MANAGER_TURBO_VERSION_SIGNATURES", "4096") or 4096)

_LOCK = threading.RLock()


@dataclass(frozen=True)
class _DefinitionBinding:
    definition: DataFileDefinition
    tags: tuple[str, ...]


_DEFINITION_BINDINGS: tuple[_DefinitionBinding, ...] | None = None
_DEFINITIONS_BY_TAG: dict[str, tuple[DataFileDefinition, ...]] | None = None
_CHANGE_SERIALS: dict[tuple[str, str], int] = {}
_GLOBAL_SERIALS: dict[str, int] = {}
_SIGNATURE_CACHE: dict[str, dict[str, Any]] = {}
_SIGNATURE_SAVED_AT: dict[str, float] = {}
_EXTERNAL_POLL_STATE: dict[tuple[str, str], tuple[float, str]] = {}
_EXTERNAL_SERIALS: dict[tuple[str, str], int] = {}


def expanded_tags(tags: Iterable[str] | None) -> tuple[str, ...]:
    expanded: set[str] = set()
    for tag in tags or ():
        text = str(tag or "").strip()
        if not text:
            continue
        expanded.add(text)
        expanded.update(TAG_ALIASES.get(text, ()))
    return tuple(sorted(expanded))


def note_data_changed(*, user_id: str | None = None, tags: Iterable[str] | None = None, path: str | os.PathLike[str] | None = None) -> None:
    """Record a write/delete/import that happened through the app.

    The cache invalidation layer also bumps runtime_epoch; this function keeps a
    separate serial used by the turbo signature cache so entries become
    unreachable immediately without filesystem polling.
    """
    safe_id = normalize_user_id(user_id) if user_id else ""
    supplied_tags = tuple(tags or ())
    changed = set(expanded_tags(supplied_tags))
    if path:
        changed.update(_tags_for_path(path, user_id=safe_id))
    global_change = not changed and not path and tags is not None
    if not changed and not global_change:
        changed.add("money_rows")

    with _LOCK:
        if global_change:
            _GLOBAL_SERIALS[safe_id] = int(_GLOBAL_SERIALS.get(safe_id, 0)) + 1
            _drop_signature_cache_locked(user_id=safe_id, tags=set())
            return
        # Tagged writes must not advance the global serial.  Doing so made every
        # cache signature change after every edit and defeated dependency-aware
        # invalidation even though the runtime epoch itself was tag-scoped.
        for tag in changed:
            key = (safe_id, tag)
            _CHANGE_SERIALS[key] = int(_CHANGE_SERIALS.get(key, 0)) + 1
        _drop_signature_cache_locked(user_id=safe_id, tags=changed)


def clear(*, user_id: str | None = None, tags: Iterable[str] | None = None) -> None:
    safe_id = normalize_user_id(user_id) if user_id else ""
    wanted = set(expanded_tags(tags or ()))
    with _LOCK:
        if not safe_id and not wanted:
            _CHANGE_SERIALS.clear()
            _GLOBAL_SERIALS.clear()
            _SIGNATURE_CACHE.clear()
            _SIGNATURE_SAVED_AT.clear()
            _EXTERNAL_POLL_STATE.clear()
            _EXTERNAL_SERIALS.clear()
            return
        _drop_signature_cache_locked(user_id=safe_id, tags=wanted)
        if safe_id:
            for key in list(_EXTERNAL_POLL_STATE):
                if key[0] == safe_id and (not wanted or key[1] in wanted):
                    _EXTERNAL_POLL_STATE.pop(key, None)
                    _EXTERNAL_SERIALS.pop(key, None)


def signature(dependencies: Iterable[str], *, user_id: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    safe_id = normalize_user_id(user_id)
    tags = expanded_tags(dependencies)
    extra_payload = extra or {}
    epoch_value = runtime_epoch.epoch(safe_id, tags)
    version_tuple = _version_tuple(safe_id, tags, epoch_value)
    app_version = _app_version_signature()
    memo_base = {
        "schema": 2,
        "user_id": safe_id,
        "tags": tags,
        "versions": version_tuple,
        "app": app_version,
        "extra": extra_payload,
    }
    memo_key = digest_payload(memo_base)
    now = time.time()
    with _LOCK:
        cached = _SIGNATURE_CACHE.get(memo_key)
        cached_at = float(_SIGNATURE_SAVED_AT.get(memo_key, 0.0) or 0.0)
        # A memoized signature may be returned only inside the external-poll
        # window.  The previous code returned it forever, so manual edits or a
        # Git pull could remain invisible until an in-app write happened.
        if cached is not None:
            if TRUST_RUNTIME_WRITES and (EXTERNAL_POLL_SECONDS <= 0 or now - cached_at < EXTERNAL_POLL_SECONDS):
                return dict(cached)

    external_digest = ""
    if _should_poll_external(safe_id, tags, now):
        external_digest = _poll_external_digest(safe_id, tags)
    else:
        external_digest = _external_serial_digest(safe_id, tags)

    payload = {
        "schema_version": 2,
        "mode": "runtime-version+throttled-poll" if TRUST_RUNTIME_WRITES else "filesystem-stat",
        "user_id": safe_id,
        "tags": tags,
        "runtime_epoch": epoch_value,
        "versions": version_tuple,
        "external": external_digest,
        "app": app_version,
        "extra": extra_payload,
    }
    payload["digest"] = digest_payload(payload)
    with _LOCK:
        _SIGNATURE_CACHE[memo_key] = dict(payload)
        _SIGNATURE_SAVED_AT[memo_key] = now
        if len(_SIGNATURE_CACHE) > MAX_SIGNATURES:
            for old_key in sorted(_SIGNATURE_SAVED_AT, key=_SIGNATURE_SAVED_AT.get)[: max(1, MAX_SIGNATURES // 8)]:
                _SIGNATURE_CACHE.pop(old_key, None)
                _SIGNATURE_SAVED_AT.pop(old_key, None)
    return payload


def stats() -> dict[str, Any]:
    with _LOCK:
        return {
            "trust_runtime_writes": TRUST_RUNTIME_WRITES,
            "external_poll_seconds": EXTERNAL_POLL_SECONDS,
            "signature_count": len(_SIGNATURE_CACHE),
            "tracked_change_serials": len(_CHANGE_SERIALS),
            "tracked_external_polls": len(_EXTERNAL_POLL_STATE),
        }


def definitions_for_tags(tags: Iterable[str]) -> tuple[DataFileDefinition, ...]:
    wanted = set(expanded_tags(tags))
    if not wanted:
        return tuple(definition for definition in all_definitions("user") if definition.file_type in {"csv", "json", "directory", "binary_folder"})
    by_tag = _definitions_by_tag()
    found: list[DataFileDefinition] = []
    seen: set[str] = set()
    for tag in wanted:
        for definition in by_tag.get(tag, ()):
            if definition.name not in seen:
                found.append(definition)
                seen.add(definition.name)
    return tuple(found)


def _version_tuple(safe_id: str, tags: tuple[str, ...], epoch_value: int) -> tuple[tuple[str, int], ...]:
    with _LOCK:
        parts = [("__global__", int(_GLOBAL_SERIALS.get(safe_id, 0))), ("__epoch__", int(epoch_value))]
        for tag in tags:
            parts.append((tag, int(_CHANGE_SERIALS.get((safe_id, tag), 0))))
        return tuple(parts)


def _should_poll_external(safe_id: str, tags: tuple[str, ...], now: float) -> bool:
    if not tags:
        return True
    if not TRUST_RUNTIME_WRITES:
        return True
    if EXTERNAL_POLL_SECONDS <= 0:
        return False
    key = (safe_id, digest_payload({"tags": tags}))
    with _LOCK:
        saved = _EXTERNAL_POLL_STATE.get(key)
        if saved is None:
            return True
        saved_at, _digest = saved
        return now - saved_at >= EXTERNAL_POLL_SECONDS


def _poll_external_digest(safe_id: str, tags: tuple[str, ...]) -> str:
    files: dict[str, Any] = {}
    for definition in definitions_for_tags(tags):
        try:
            path = resolve_definition_path(definition, user_id=safe_id)
        except Exception:
            path = Path(definition.relative_path)
        files[definition.name] = _fast_stat(path, schema_version=definition.schema_version)
    digest = digest_payload({"files": files})
    poll_key = (safe_id, digest_payload({"tags": tags}))
    with _LOCK:
        old = _EXTERNAL_POLL_STATE.get(poll_key)
        if old is not None and old[1] != digest:
            _EXTERNAL_SERIALS[poll_key] = int(_EXTERNAL_SERIALS.get(poll_key, 0)) + 1
            _drop_signature_cache_locked(user_id=safe_id, tags=set(tags))
        _EXTERNAL_POLL_STATE[poll_key] = (time.time(), digest)
    return digest_payload({"digest": digest, "serial": _EXTERNAL_SERIALS.get(poll_key, 0)})


def _external_serial_digest(safe_id: str, tags: tuple[str, ...]) -> str:
    poll_key = (safe_id, digest_payload({"tags": tags}))
    with _LOCK:
        saved = _EXTERNAL_POLL_STATE.get(poll_key)
        serial = int(_EXTERNAL_SERIALS.get(poll_key, 0))
        return digest_payload({"digest": saved[1] if saved else "not-polled", "serial": serial})


def _fast_stat(path: Path, *, schema_version: int = 1) -> dict[str, Any]:
    try:
        stat = path.stat()
        if path.is_dir():
            return _fast_dir_stat(path, schema_version=schema_version)
        return {
            "exists": True,
            "mtime_ns": int(stat.st_mtime_ns),
            "size": int(stat.st_size),
            "schema_version": int(schema_version or 1),
            "is_dir": False,
        }
    except Exception:
        return {"exists": False, "mtime_ns": 0, "size": 0, "schema_version": int(schema_version or 1), "is_dir": False}


def _fast_dir_stat(path: Path, *, schema_version: int = 1) -> dict[str, Any]:
    # Directories are expensive to scan recursively.  For hot navigation use the
    # directory's own mtime and only count direct files; full recursive integrity
    # checks can still be run from dedicated maintenance pages.
    try:
        stat = path.stat()
        entries = 0
        total_size = 0
        try:
            for child in path.iterdir():
                if child.is_file():
                    entries += 1
                    total_size += int(child.stat().st_size)
        except Exception:
            pass
        return {
            "exists": True,
            "mtime_ns": int(stat.st_mtime_ns),
            "size": int(total_size),
            "entries": int(entries),
            "schema_version": int(schema_version or 1),
            "is_dir": True,
        }
    except Exception:
        return {"exists": False, "mtime_ns": 0, "size": 0, "entries": 0, "schema_version": int(schema_version or 1), "is_dir": True}


def _definition_bindings() -> tuple[_DefinitionBinding, ...]:
    global _DEFINITION_BINDINGS
    if _DEFINITION_BINDINGS is not None:
        return _DEFINITION_BINDINGS
    bindings: list[_DefinitionBinding] = []
    for definition in all_definitions("user"):
        if definition.file_type not in {"csv", "json", "directory", "binary_folder"}:
            continue
        tags = set(definition.invalidation_tags or ()) | {definition.name, definition.relative_path}
        for broad, aliases in TAG_ALIASES.items():
            if definition.name in aliases or tags.intersection(aliases):
                tags.add(broad)
        bindings.append(_DefinitionBinding(definition=definition, tags=tuple(sorted(tags))))
    _DEFINITION_BINDINGS = tuple(bindings)
    return _DEFINITION_BINDINGS


def _definitions_by_tag() -> dict[str, tuple[DataFileDefinition, ...]]:
    global _DEFINITIONS_BY_TAG
    if _DEFINITIONS_BY_TAG is not None:
        return _DEFINITIONS_BY_TAG
    result: dict[str, list[DataFileDefinition]] = {}
    for binding in _definition_bindings():
        for tag in binding.tags:
            result.setdefault(tag, []).append(binding.definition)
    _DEFINITIONS_BY_TAG = {key: tuple(value) for key, value in result.items()}
    return _DEFINITIONS_BY_TAG


def _tags_for_path(path: str | os.PathLike[str], *, user_id: str = "") -> tuple[str, ...]:
    target = Path(path)
    relative = ""
    if user_id:
        try:
            from money_manager.config.install_paths import USERS_DIR

            relative = target.resolve().relative_to((USERS_DIR / normalize_user_id(user_id)).resolve()).as_posix()
        except Exception:
            relative = ""
    target_name = relative or target.name
    tags: set[str] = set()
    for binding in _definition_bindings():
        definition = binding.definition
        if target_name == definition.relative_path or target.name == definition.relative_path or target.name == definition.name:
            tags.update(binding.tags)
    return tuple(sorted(tags or {"money_rows"}))


def _app_version_signature() -> dict[str, Any]:
    try:
        app_version = load_app_version()
        return {
            "version": str(app_version.get("version") or ""),
            "data_schema_current": app_version.get("data_schema_current"),
        }
    except Exception:
        return {"version": "", "data_schema_current": None}


def _drop_signature_cache_locked(*, user_id: str = "", tags: set[str] | None = None) -> None:
    # Signature keys are digests, so selective removal by content is impossible.
    # Clearing this small map is cheaper than any risk of serving old keys.
    _SIGNATURE_CACHE.clear()
    _SIGNATURE_SAVED_AT.clear()
