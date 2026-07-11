from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from money_manager.config.install_paths import GLOBAL_CACHE_DIR

_FALSE_VALUES = {"0", "false", "no", "off", "disabled"}


def clear_cache_on_startup() -> dict[str, Any]:
    """Optionally clear generated cache files when the app starts.

    Cache entries already carry application versions, source fingerprints, user
    IDs, dependency tags, and TTL metadata.  Deleting the whole cache on every
    launch therefore discarded valid calculations and forced the first visit to
    every page to recompute them.  The safe default is now to preserve the cache
    and let fingerprint validation ignore stale entries.

    Set ``MONEY_MANAGER_CLEAR_CACHE_ON_START=1`` only for troubleshooting or a
    deliberate cold-start test.
    """
    flag = str(os.environ.get("MONEY_MANAGER_CLEAR_CACHE_ON_START", "0") or "0").strip().lower()
    cache_dir = Path(GLOBAL_CACHE_DIR)

    if flag in _FALSE_VALUES:
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            return {"enabled": False, "removed": False, "path": str(cache_dir), "error": str(exc)}
        return {"enabled": False, "removed": False, "preserved": True, "path": str(cache_dir)}

    removed = False
    try:
        if cache_dir.exists():
            shutil.rmtree(cache_dir)
            removed = True
        cache_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return {"enabled": True, "removed": removed, "path": str(cache_dir), "error": str(exc)}

    try:
        from money_manager.cache import process_cache, request_cache

        process_cache.clear()
        request_cache.clear_user()
    except Exception:
        pass

    try:
        from money_manager.cache.source_fingerprint_service import clear_fingerprint_caches

        clear_fingerprint_caches()
    except Exception:
        pass

    return {"enabled": True, "removed": removed, "preserved": False, "path": str(cache_dir)}
