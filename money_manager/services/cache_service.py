"""Small disk cache for expensive money-manager calculations.

The app remains CSV/JSON-first.  This service only stores derived results in
``data/cache`` and reuses them when the underlying data-file fingerprint is still
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

from money_manager.config.paths import CACHE_DIR

CACHE_FORMAT_VERSION = 1
WARMUP_DEBOUNCE_SECONDS = 0.8

_LOCK = threading.RLock()
_BACKGROUND_TIMER: threading.Timer | None = None
_BACKGROUND_RUNNING = False
_STARTUP_WARMED = False


def cached_calculation(
    key: str,
    builder: Callable[[], Any],
    *,
    extra_fingerprint: dict[str, Any] | None = None,
    allow_stale_on_error: bool = False,
) -> Any:
    """Return a cached calculation when all tracked input files are unchanged.

    ``builder`` is still the source of truth.  It is called whenever the cache is
    missing, stale, unreadable, or incompatible with the current cache format.
    """
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
    """Fingerprint every source file that can affect cached calculations."""
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
        "files": files,
        "extra": extra or {},
    }


def notify_data_changed() -> None:
    """Schedule a best-effort background cache refresh after a data write."""
    schedule_cache_refresh()


def schedule_cache_refresh(delay: float = WARMUP_DEBOUNCE_SECONDS) -> None:
    """Debounce background warmups so several writes trigger one refresh."""
    global _BACKGROUND_TIMER

    def _run() -> None:
        warm_default_calculations()

    with _LOCK:
        if _BACKGROUND_TIMER is not None:
            try:
                _BACKGROUND_TIMER.cancel()
            except Exception:
                pass
        _BACKGROUND_TIMER = threading.Timer(delay, _run)
        _BACKGROUND_TIMER.daemon = True
        _BACKGROUND_TIMER.start()


def warm_app_cache_async() -> None:
    """Start one best-effort cache warmup thread after Flask creates the app."""
    global _STARTUP_WARMED
    with _LOCK:
        if _STARTUP_WARMED:
            return
        _STARTUP_WARMED = True

    thread = threading.Thread(target=warm_default_calculations, name="money-manager-cache-warmup", daemon=True)
    thread.start()


def warm_default_calculations() -> None:
    """Precompute the pages/metrics listed in the path registry.

    Any single warmup failure is ignored so the app never fails to start because
    of the cache layer.  The next normal page call will still calculate directly
    if its cache is stale.
    """
    global _BACKGROUND_RUNNING
    with _LOCK:
        if _BACKGROUND_RUNNING:
            return
        _BACKGROUND_RUNNING = True

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
            _BACKGROUND_RUNNING = False


def cache_status() -> dict[str, Any]:
    """Return lightweight status data for debugging."""
    CACHE_DIR.mkdir(exist_ok=True, parents=True)
    records = []
    for path in sorted(CACHE_DIR.glob("*.pkl")):
        try:
            stat = path.stat()
            records.append({"file": path.name, "size": stat.st_size, "mtime": stat.st_mtime})
        except OSError:
            continue
    return {
        "dir": str(CACHE_DIR),
        "records": records,
        "fingerprint": data_fingerprint(),
    }


def _call_warmup_function(key: str, func: Callable[..., Any]) -> None:
    # These functions have optional flags and/or cached wrappers.  Calling them
    # with their default arguments preserves the existing runtime behaviour.
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


def _cache_path(key: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in key)
    return CACHE_DIR / f"{safe}.pkl"


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
        CACHE_DIR.mkdir(exist_ok=True, parents=True)
        record = {
            "format": CACHE_FORMAT_VERSION,
            "key": key,
            "saved_at": time.time(),
            "fingerprint": fingerprint,
            "value": value,
        }
        target = _cache_path(key)
        with NamedTemporaryFile("wb", delete=False, dir=str(CACHE_DIR), prefix=f".{target.stem}.", suffix=".tmp") as tmp:
            pickle.dump(record, tmp, protocol=pickle.HIGHEST_PROTOCOL)
            temp_name = tmp.name
        Path(temp_name).replace(target)
        _write_manifest()
    except Exception:
        return


def _write_manifest() -> None:
    try:
        CACHE_DIR.mkdir(exist_ok=True, parents=True)
        payload = {
            "format": CACHE_FORMAT_VERSION,
            "updated_at": time.time(),
            "cache_dir": str(CACHE_DIR),
            "input_files": [str(path) for path in _cache_input_files()],
            "calculation_entrypoints": _calculation_entrypoints(),
        }
        target = CACHE_DIR / "manifest.json"
        with NamedTemporaryFile("w", delete=False, dir=str(CACHE_DIR), prefix=".manifest.", suffix=".tmp", encoding="utf-8") as tmp:
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
