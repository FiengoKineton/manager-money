from __future__ import annotations

from collections.abc import Callable
from typing import Any

from money_manager.cache.cache_manager import get_or_compute
from money_manager.cache.cache_registry import get_cache_definition
from money_manager.performance import fast_memory_cache


def cached_context(
    name: str,
    builder: Callable[[], Any],
    *,
    params: dict[str, Any] | None = None,
    extra_fingerprint: dict[str, Any] | None = None,
    allow_stale_on_error: bool = False,
) -> Any:
    definition = get_cache_definition(name)
    if fast_memory_cache.is_enabled():
        try:
            return fast_memory_cache.get_or_compute(
                name,
                builder,
                dependencies=definition.dependencies,
                params=params or {},
                extra=extra_fingerprint or {},
                ttl_seconds=definition.ttl_seconds,
            )
        except Exception:
            if not allow_stale_on_error:
                pass
    return get_or_compute(
        name,
        builder,
        params=params or {},
        extra_fingerprint=extra_fingerprint,
        allow_stale_on_error=allow_stale_on_error,
        definition=definition,
    )
