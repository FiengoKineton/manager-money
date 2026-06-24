from __future__ import annotations

import importlib
from typing import Any

_CACHE_MANAGER_EXPORTS = {
    "cache_status",
    "data_fingerprint",
    "get_or_compute",
}
_CACHE_INVALIDATION_EXPORTS = {
    "clear_user_cache",
    "cleanup_stale_entries",
    "invalidate_all",
    "invalidate_key",
    "invalidate_tags",
}
_CACHE_MODULE_EXPORTS = {
    "file_read_cache",
    "process_cache",
    "request_cache",
    "runtime_epoch",
}


def __getattr__(name: str) -> Any:
    """Lazy cache package exports.

    Importing ``money_manager.cache`` used to import ``cache_manager`` eagerly.
    That made startup fragile because ``secure_storage`` imports the decrypted
    file cache while storage/cache modules also import secure storage.  Keeping
    package exports lazy preserves the old public API without creating the
    startup circular import.
    """
    if name in _CACHE_MODULE_EXPORTS:
        module = importlib.import_module(f"money_manager.cache.{name}")
        globals()[name] = module
        return module
    if name in _CACHE_MANAGER_EXPORTS:
        module = importlib.import_module("money_manager.cache.cache_manager")
        value = getattr(module, name)
        globals()[name] = value
        return value
    if name in _CACHE_INVALIDATION_EXPORTS:
        module = importlib.import_module("money_manager.cache.cache_invalidation")
        value = getattr(module, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = sorted(_CACHE_MANAGER_EXPORTS | _CACHE_INVALIDATION_EXPORTS | _CACHE_MODULE_EXPORTS)
