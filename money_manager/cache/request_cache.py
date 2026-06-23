from __future__ import annotations

from typing import Any

try:
    from flask import g, has_request_context
except Exception:  # pragma: no cover
    g = None  # type: ignore

    def has_request_context() -> bool:
        return False

REQUEST_CACHE_ATTR = "_money_manager_request_cache"


def init_request_cache() -> None:
    if has_request_context():
        setattr(g, REQUEST_CACHE_ATTR, {})


def clear_request_cache(error: BaseException | None = None) -> None:
    if has_request_context() and hasattr(g, REQUEST_CACHE_ATTR):
        try:
            getattr(g, REQUEST_CACHE_ATTR).clear()
        except Exception:
            pass


def enabled() -> bool:
    return has_request_context()


def _store() -> dict[str, Any] | None:
    if not has_request_context():
        return None
    store = getattr(g, REQUEST_CACHE_ATTR, None)
    if store is None:
        store = {}
        setattr(g, REQUEST_CACHE_ATTR, store)
    return store


def get(key: str, default: Any = None) -> Any:
    store = _store()
    if store is None:
        return default
    return store.get(str(key), default)


def set(key: str, value: Any) -> None:
    store = _store()
    if store is not None:
        store[str(key)] = value


def delete_prefix(prefix: str) -> None:
    store = _store()
    if not store:
        return
    prefix = str(prefix)
    for key in list(store.keys()):
        if key.startswith(prefix):
            store.pop(key, None)


def clear_user(user_id: str | None = None) -> None:
    store = _store()
    if store is not None:
        store.clear()
