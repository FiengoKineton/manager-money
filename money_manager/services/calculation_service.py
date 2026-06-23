from __future__ import annotations

from collections.abc import Callable
from typing import Any

from money_manager.cache.cache_manager import get_or_compute


def cached_context(name: str, builder: Callable[[], Any], *, params: dict[str, Any] | None = None, allow_stale_on_error: bool = False) -> Any:
    return get_or_compute(name, builder, params=params or {}, allow_stale_on_error=allow_stale_on_error)
