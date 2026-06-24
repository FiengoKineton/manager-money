from __future__ import annotations

import threading
from collections import defaultdict
from typing import Iterable

from money_manager.config.user_paths import normalize_user_id

_LOCK = threading.RLock()
_GLOBAL_EPOCH: dict[str, int] = defaultdict(int)
_TAG_EPOCH: dict[tuple[str, str], int] = defaultdict(int)


def _clean_tags(tags: Iterable[str] | None = None) -> list[str]:
    return [str(tag or "").strip() for tag in (tags or ()) if str(tag or "").strip()]


def bump(user_id: str | None = None, tags: Iterable[str] | None = None) -> int:
    """Bump cache freshness counters.

    The previous implementation incremented the global epoch for every tagged
    write.  That made a tiny change, for example categories.json or pending.csv,
    invalidate unrelated dashboard/account/transaction caches.  Tagged writes now
    touch only their tags; a true global bump still happens when no tags are
    supplied.
    """
    safe_id = normalize_user_id(user_id) if user_id else ""
    wanted = _clean_tags(tags)
    with _LOCK:
        if not wanted:
            _GLOBAL_EPOCH[safe_id] += 1
            return int(_GLOBAL_EPOCH[safe_id])
        for tag in wanted:
            _TAG_EPOCH[(safe_id, tag)] += 1
        return sum(int(_TAG_EPOCH.get((safe_id, tag), 0)) for tag in wanted)


def epoch(user_id: str | None = None, tags: Iterable[str] | None = None) -> int:
    safe_id = normalize_user_id(user_id) if user_id else ""
    wanted = _clean_tags(tags)
    with _LOCK:
        if not wanted:
            return int(_GLOBAL_EPOCH.get(safe_id, 0))
        # Do not mix the global epoch into tagged fingerprints.  This keeps a
        # write to one feature from forcing every other feature to recompute.
        return sum(int(_TAG_EPOCH.get((safe_id, tag), 0)) for tag in wanted)


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
