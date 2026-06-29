from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from money_manager.config.install_paths import GLOBAL_CACHE_DIR

_FALSE_VALUES = {"0", "false", "no", "off", "disabled"}


def clear_cache_on_startup() -> dict[str, Any]:
    """Clear local generated cache files when the app starts.

    This removes only MoneyManagerData/cache, not MoneyManagerData/data.  It is
    enabled by default because the app is commonly synced between devices via Git
    and stale per-device cache files can make pages show outdated account/card
    scopes after a pull.

    Set MONEY_MANAGER_CLEAR_CACHE_ON_START=0 to disable it.
    """
    flag = str(os.environ.get("MONEY_MANAGER_CLEAR_CACHE_ON_START", "1") or "1").strip().lower()
    if flag in _FALSE_VALUES:
        return {"enabled": False, "removed": False, "path": str(GLOBAL_CACHE_DIR)}

    cache_dir = Path(GLOBAL_CACHE_DIR)
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

    return {"enabled": True, "removed": removed, "path": str(cache_dir)}
