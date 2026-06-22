"""Small per-user disk cache for expensive money-manager calculations.

The app remains CSV/JSON-first.  Derived records are stored in each user's
``cache`` folder and reused only while that user's input-file fingerprint is
current.  If a cache read/write fails, callers transparently fall back to the
original calculation.
"""

from __future__ import annotations

import copy
import importlib
import json
import pickle
import threading
import time
from collections.abc import Callable
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from money_manager.config.user_paths import get_current_user_id, user_cache_dir, using_user

CACHE_FORMAT_VERSION = 1
WARMUP_DEBOUNCE_SECONDS = 0.8

_LOCK = threading.RLock()
_BACKGROUND_TIMERS: dict[str, threading.Timer] = {}
_BACKGROUND_RUNNING: set[str] = set()
_STARTUP_WARMED: set[str] = set()


def cached_calculation(
    key: str,
    builder: Callable[[], Any],
    *,
    extra_fingerprint: dict[str, Any] | None = None,
    allow_stale_on_error: bool = False,
) -> Any:
    fingerprint = data_fingerprint(extra=extra_fingerprint)
    cached = _read_cache_record(key)

    if cached and cached.get("fingerprint") == fingerprint:
        return _safe_copy(cached.get("value"))

    try:
        value = builder()
    except Exception:
        if allow_stale_on_error and cached and "value" in cached:
            return _safe_copy(cached.get("value"))
        raise

    _write_cache_record(key, value, fingerprint)
    return _safe_copy(value)


def data_fingerprint(*, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    files: dict[str, dict[str, Any]] = {}
    for path in _cache_input_files():
        try:
            stat = path.stat()
            files[str(path)] = {
                "exists": True,
                "mtime_ns": int(stat.st_mtime_ns),
                "size": int(stat.st_size),
            }
        except OSError:
            files[str(path)] = {"exists": False, "mtime_ns": 0, "size": 0}

    return {
        "format": CACHE_FORMAT_VERSION,
        "user_id": get_current_user_id(),
        "files": files,
        "extra": extra or {},
    }


def notify_data_changed() -> None:
    user_id = get_current_user_id()
    if user_id:
        schedule_cache_refresh(user_id=user_id)


def schedule_cache_refresh(delay: float = WARMUP_DEBOUNCE_SECONDS, *, user_id: str | None = None) -> None:
    user_id = user_id or get_current_user_id()
    if not user_id:
        return

    def _run() -> None:
        with using_user(user_id):
            warm_default_calculations(user_id=user_id)

    with _LOCK:
        old_timer = _BACKGROUND_TIMERS.get(user_id)
        if old_timer is not None:
            try:
                old_timer.cancel()
            except Exception:
                pass
        timer = threading.Timer(delay, _run)
        timer.daemon = True
        _BACKGROUND_TIMERS[user_id] = timer
        timer.start()


def warm_app_cache_async() -> None:
    user_id = get_current_user_id()
    if not user_id:
        return
    with _LOCK:
        if user_id in _STARTUP_WARMED:
            return
        _STARTUP_WARMED.add(user_id)

    def _run() -> None:
        with using_user(user_id):
            warm_default_calculations(user_id=user_id)

    thread = threading.Thread(target=_run, name=f"money-manager-cache-warmup-{user_id}", daemon=True)
    thread.start()


def warm_default_calculations(*, user_id: str | None = None) -> None:
    user_id = user_id or get_current_user_id()
    if not user_id:
        return
    with _LOCK:
        if user_id in _BACKGROUND_RUNNING:
            return
        _BACKGROUND_RUNNING.add(user_id)

    try:
        for key, import_path in _calculation_entrypoints().items():
            try:
                func = _import_from_string(import_path)
                _call_warmup_function(key, func)
            except Exception:
                continue
        _write_manifest()
    finally:
        with _LOCK:
            _BACKGROUND_RUNNING.discard(user_id)


def cache_status() -> dict[str, Any]:
    cache_dir = _cache_dir()
    cache_dir.mkdir(exist_ok=True, parents=True)
    records = []
    for path in sorted(cache_dir.glob("*.pkl")):
        try:
            stat = path.stat()
            records.append({"file": path.name, "size": stat.st_size, "mtime": stat.st_mtime})
        except OSError:
            continue
    return {
        "dir": str(cache_dir),
        "records": records,
        "fingerprint": data_fingerprint(),
    }


def _call_warmup_function(key: str, func: Callable[..., Any]) -> None:
    if key == "investment.overview_snapshot":
        func(refresh=False)
    elif key == "investment.habit_snapshot":
        func(refresh=False)
    else:
        func()


def _cache_input_files() -> tuple[Path, ...]:
    try:
        from money_manager.config.path_registry import CACHE_INPUT_FILES

        return CACHE_INPUT_FILES
    except Exception:
        return tuple()


def _calculation_entrypoints() -> dict[str, str]:
    try:
        from money_manager.config.path_registry import CALCULATION_ENTRYPOINTS

        return dict(CALCULATION_ENTRYPOINTS)
    except Exception:
        return {}


def _import_from_string(import_path: str) -> Callable[..., Any]:
    module_name, attr_name = import_path.rsplit(".", 1)
    module = importlib.import_module(module_name)
    return getattr(module, attr_name)


def _cache_dir() -> Path:
    return Path(user_cache_dir())


def _cache_path(key: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in key)
    return _cache_dir() / f"{safe}.pkl"


def _read_cache_record(key: str) -> dict[str, Any] | None:
    path = _cache_path(key)
    try:
        with path.open("rb") as file:
            record = pickle.load(file)
    except Exception:
        return None
    if not isinstance(record, dict):
        return None
    if record.get("format") != CACHE_FORMAT_VERSION:
        return None
    return record


def _write_cache_record(key: str, value: Any, fingerprint: dict[str, Any]) -> None:
    try:
        cache_dir = _cache_dir()
        cache_dir.mkdir(exist_ok=True, parents=True)
        record = {
            "format": CACHE_FORMAT_VERSION,
            "key": key,
            "saved_at": time.time(),
            "fingerprint": fingerprint,
            "value": value,
        }
        target = _cache_path(key)
        with NamedTemporaryFile("wb", delete=False, dir=str(cache_dir), prefix=f".{target.stem}.", suffix=".tmp") as tmp:
            pickle.dump(record, tmp, protocol=pickle.HIGHEST_PROTOCOL)
            temp_name = tmp.name
        Path(temp_name).replace(target)
        _write_manifest()
    except Exception:
        return


def _write_manifest() -> None:
    try:
        cache_dir = _cache_dir()
        cache_dir.mkdir(exist_ok=True, parents=True)
        payload = {
            "format": CACHE_FORMAT_VERSION,
            "updated_at": time.time(),
            "user_id": get_current_user_id(),
            "cache_dir": str(cache_dir),
            "input_files": [str(path) for path in _cache_input_files()],
            "calculation_entrypoints": _calculation_entrypoints(),
        }
        target = cache_dir / "manifest.json"
        with NamedTemporaryFile("w", delete=False, dir=str(cache_dir), prefix=".manifest.", suffix=".tmp", encoding="utf-8") as tmp:
            json.dump(payload, tmp, indent=2)
            temp_name = tmp.name
        Path(temp_name).replace(target)
    except Exception:
        return


def _safe_copy(value: Any) -> Any:
    try:
        return copy.deepcopy(value)
    except Exception:
        return value
