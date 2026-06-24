from __future__ import annotations

import threading
from collections import defaultdict
from typing import Iterable

from money_manager.config.user_paths import normalize_user_id

_LOCK = threading.RLock()
_GLOBAL_EPOCH: dict[str, int] = defaultdict(int)
_TAG_EPOCH: dict[tuple[str, str], int] = defaultdict(int)


def bump(user_id: str | None = None, tags: Iterable[str] | None = None) -> int:
    safe_id = normalize_user_id(user_id) if user_id else ""
    with _LOCK:
        _GLOBAL_EPOCH[safe_id] += 1
        current = _GLOBAL_EPOCH[safe_id]
        for tag in tags or ():
            text = str(tag or "").strip()
            if text:
                _TAG_EPOCH[(safe_id, text)] += 1
        return current


def epoch(user_id: str | None = None, tags: Iterable[str] | None = None) -> int:
    safe_id = normalize_user_id(user_id) if user_id else ""
    wanted = [str(tag or "").strip() for tag in (tags or ()) if str(tag or "").strip()]
    with _LOCK:
        if not wanted:
            return int(_GLOBAL_EPOCH.get(safe_id, 0))
        total = int(_GLOBAL_EPOCH.get(safe_id, 0))
        for tag in wanted:
            total += int(_TAG_EPOCH.get((safe_id, tag), 0))
        return total


def reset(user_id: str | None = None) -> None:
    safe_id = normalize_user_id(user_id) if user_id else ""
    with _LOCK:
        if safe_id:
            _GLOBAL_EPOCH.pop(safe_id, None)
            for key in list(_TAG_EPOCH):
                if key[0] == safe_id:
                    _TAG_EPOCH.pop(key, None)
        else:
            _GLOBAL_EPOCH.clear()
            _TAG_EPOCH.clear()
