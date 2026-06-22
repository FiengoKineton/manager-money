from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping, Sequence

from money_manager.config.navigation_registry import DEFAULT_NAVIGATION as NAVIGATION_REGISTRY
from money_manager.config.navigation_registry import navigation_registry, registry_group_ids, registry_page_ids
from money_manager.config.user_defaults import DEFAULT_NAVIGATION
from money_manager.services._user_config import load_user_config, save_user_config

NAVIGATION_FILE = "navigation.json"
PROTECTED_PAGE_IDS = {"profile", "logout"}


def load_navigation_config(user_id: str | None = None) -> dict[str, Any]:
    return validate_navigation_config(load_user_config(NAVIGATION_FILE, user_id=user_id))


def save_navigation_config(config: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    return save_user_config(NAVIGATION_FILE, validate_navigation_config(config), user_id=user_id)


def validate_navigation_config(config: Mapping[str, Any] | None) -> dict[str, Any]:
    """Clean user navigation settings against the current registry.

    Unknown/deleted page IDs and groups are discarded so a stale
    ``navigation.json`` can never break the app. New registry pages remain
    visible by default because only explicit hidden page IDs are stored.
    """
    incoming = dict(config or {})
    valid_pages = registry_page_ids()
    valid_groups = registry_group_ids()

    hidden_pages = [page_id for page_id in _unique_keys(incoming.get("hidden_pages", [])) if page_id in valid_pages]
    hidden_pages = [page_id for page_id in hidden_pages if page_id not in PROTECTED_PAGE_IDS]

    custom_order = _normalize_custom_order(incoming.get("custom_order", {}), valid_groups=valid_groups, valid_pages=valid_pages)
    group_order = _normalize_group_order(incoming.get("group_order", []), valid_groups=valid_groups)
    collapsed_groups = [group_id for group_id in _unique_keys(incoming.get("collapsed_groups", [])) if group_id in valid_groups]

    return {
        "schema_version": int(incoming.get("schema_version") or DEFAULT_NAVIGATION.get("schema_version") or 1),
        "hidden_pages": hidden_pages,
        "custom_order": custom_order,
        "group_order": group_order,
        "collapsed_groups": collapsed_groups,
    }


def get_effective_navigation(
    *,
    include_hidden: bool = False,
    current_endpoint: str | None = None,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return registry groups merged with the current user's preferences."""
    config = load_navigation_config(user_id=user_id)
    hidden = set(config.get("hidden_pages", []))
    collapsed = set(config.get("collapsed_groups", []))
    endpoint = str(current_endpoint or "")

    groups = _ordered_groups(navigation_registry(), config.get("group_order", []))
    effective_groups: list[dict[str, Any]] = []

    for group in groups:
        group_id = str(group.get("group_id") or "")
        ordered_items = _ordered_items(group, config.get("custom_order", {}).get(group_id, []))
        effective_items: list[dict[str, Any]] = []

        for item in ordered_items:
            page_id = str(item.get("page_id") or "")
            default_visible = bool(item.get("default_visible", True))
            is_hidden = page_id in hidden or not default_visible
            if is_hidden and not include_hidden:
                continue

            active_endpoints = [str(ep) for ep in item.get("active_endpoints", []) if ep]
            if not active_endpoints:
                active_endpoints = [str(item.get("endpoint") or "")]

            clean_item = deepcopy(item)
            clean_item["is_visible"] = not is_hidden
            clean_item["is_hidden"] = is_hidden
            clean_item["is_active"] = endpoint in active_endpoints
            clean_item["can_hide"] = page_id not in PROTECTED_PAGE_IDS
            clean_item["active_endpoints"] = active_endpoints
            effective_items.append(clean_item)

        if not effective_items and not include_hidden:
            continue

        is_active = any(item.get("is_active") for item in effective_items)
        clean_group = deepcopy(group)
        clean_group["items"] = effective_items
        clean_group["is_collapsed"] = group_id in collapsed
        clean_group["is_open"] = bool(group.get("default_open", False)) and group_id not in collapsed
        clean_group["is_active"] = is_active
        effective_groups.append(clean_group)

    return effective_groups


def hidden_pages(user_id: str | None = None) -> list[str]:
    return load_navigation_config(user_id=user_id).get("hidden_pages", [])


def is_page_hidden(page_id: str, user_id: str | None = None) -> bool:
    return _safe_key(page_id) in set(hidden_pages(user_id=user_id))


def hide_page(page_id: str, user_id: str | None = None) -> dict[str, Any]:
    key = _safe_key(page_id)
    config = load_navigation_config(user_id=user_id)
    if key in registry_page_ids() and key not in PROTECTED_PAGE_IDS and key not in config["hidden_pages"]:
        config["hidden_pages"].append(key)
    return save_navigation_config(config, user_id=user_id)


def show_page(page_id: str, user_id: str | None = None) -> dict[str, Any]:
    key = _safe_key(page_id)
    config = load_navigation_config(user_id=user_id)
    config["hidden_pages"] = [item for item in config["hidden_pages"] if item != key]
    return save_navigation_config(config, user_id=user_id)


def restore_page(page_id: str, user_id: str | None = None) -> dict[str, Any]:
    # Backward-compatible alias for older code.
    return show_page(page_id, user_id=user_id)


def move_page(
    page_id: str,
    direction: str | None = None,
    target_index: int | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    key = _safe_key(page_id)
    if key not in registry_page_ids():
        return load_navigation_config(user_id=user_id)

    registry_group = _find_group_for_page(key)
    if not registry_group:
        return load_navigation_config(user_id=user_id)

    group_id = str(registry_group.get("group_id") or "")
    config = load_navigation_config(user_id=user_id)
    current_order = [item["page_id"] for item in _ordered_items(registry_group, config.get("custom_order", {}).get(group_id, []))]
    if key not in current_order:
        return config

    old_index = current_order.index(key)
    if target_index is not None:
        new_index = max(0, min(int(target_index), len(current_order) - 1))
    else:
        step = -1 if str(direction or "").casefold() == "up" else 1 if str(direction or "").casefold() == "down" else 0
        new_index = max(0, min(old_index + step, len(current_order) - 1))

    if new_index != old_index:
        current_order.insert(new_index, current_order.pop(old_index))
        config.setdefault("custom_order", {})[group_id] = current_order
    return save_navigation_config(config, user_id=user_id)


def restore_default_navigation(user_id: str | None = None) -> dict[str, Any]:
    return save_navigation_config(deepcopy(DEFAULT_NAVIGATION), user_id=user_id)


def set_group_collapsed(group_id: str, collapsed: bool, user_id: str | None = None) -> dict[str, Any]:
    key = _safe_key(group_id)
    config = load_navigation_config(user_id=user_id)
    if key not in registry_group_ids():
        return config
    current = [item for item in config.get("collapsed_groups", []) if item != key]
    if collapsed:
        current.append(key)
    config["collapsed_groups"] = current
    return save_navigation_config(config, user_id=user_id)


def collapse_group(group_id: str, user_id: str | None = None) -> dict[str, Any]:
    return set_group_collapsed(group_id, True, user_id=user_id)


def expand_group(group_id: str, user_id: str | None = None) -> dict[str, Any]:
    return set_group_collapsed(group_id, False, user_id=user_id)


def set_custom_order(order: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    config = load_navigation_config(user_id=user_id)
    config["custom_order"] = _normalize_custom_order(
        order,
        valid_groups=registry_group_ids(),
        valid_pages=registry_page_ids(),
    )
    return save_navigation_config(config, user_id=user_id)


def set_group_order(order: Sequence[Any] | Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    config = load_navigation_config(user_id=user_id)
    config["group_order"] = _normalize_group_order(order, valid_groups=registry_group_ids())
    return save_navigation_config(config, user_id=user_id)


def ensure_navigation_config(user_id: str | None = None) -> dict[str, Any]:
    return load_navigation_config(user_id=user_id)


def navigation_registry_structure() -> list[dict[str, Any]]:
    """Expose the full registry for debugging/tests/documentation."""
    return deepcopy(NAVIGATION_REGISTRY)


def _ordered_groups(groups: list[dict[str, Any]], custom_group_order: Sequence[str]) -> list[dict[str, Any]]:
    group_by_id = {str(group.get("group_id") or ""): group for group in groups}
    ordered: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group_id in custom_group_order:
        group = group_by_id.get(group_id)
        if group and group_id not in seen:
            ordered.append(group)
            seen.add(group_id)
    leftovers = [group for group in groups if str(group.get("group_id") or "") not in seen]
    leftovers.sort(key=lambda group: int(group.get("default_order") or 0))
    return ordered + leftovers


def _ordered_items(group: Mapping[str, Any], custom_item_order: Sequence[str]) -> list[dict[str, Any]]:
    items = [deepcopy(item) for item in group.get("items", [])]
    item_by_id = {str(item.get("page_id") or ""): item for item in items}
    ordered: list[dict[str, Any]] = []
    seen: set[str] = set()
    for page_id in custom_item_order:
        item = item_by_id.get(page_id)
        if item and page_id not in seen:
            ordered.append(item)
            seen.add(page_id)
    leftovers = [item for item in items if str(item.get("page_id") or "") not in seen]
    leftovers.sort(key=lambda item: int(item.get("default_order") or 0))
    return ordered + leftovers


def _find_group_for_page(page_id: str) -> dict[str, Any] | None:
    for group in navigation_registry():
        if any(str(item.get("page_id") or "") == page_id for item in group.get("items", [])):
            return group
    return None


def _normalize_custom_order(value: Any, *, valid_groups: set[str], valid_pages: set[str]) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}

    result: dict[str, list[str]] = {}

    # New shape: {"group_id": ["page_id", ...]}.
    for raw_group_id, raw_order in value.items():
        group_id = _safe_key(raw_group_id)
        if group_id not in valid_groups:
            continue

        page_order: list[str] = []
        if isinstance(raw_order, list):
            page_order = _unique_keys(raw_order)
        elif isinstance(raw_order, dict):
            # Backward-compatible shape: {"page_id": order_number}.
            ranked = []
            for raw_page_id, rank in raw_order.items():
                page_id = _safe_key(raw_page_id)
                try:
                    ranked.append((int(rank), page_id))
                except (TypeError, ValueError):
                    continue
            page_order = [page_id for _, page_id in sorted(ranked)]

        page_order = [page_id for page_id in page_order if page_id in valid_pages]
        if page_order:
            result[group_id] = page_order

    # Older v08 shape: {"page_id": order_number}. Convert it by page group.
    if not result:
        legacy_ranked: list[tuple[int, str]] = []
        for raw_page_id, rank in value.items():
            page_id = _safe_key(raw_page_id)
            if page_id not in valid_pages:
                continue
            try:
                legacy_ranked.append((int(rank), page_id))
            except (TypeError, ValueError):
                continue
        for _, page_id in sorted(legacy_ranked):
            group = _find_group_for_page(page_id)
            if not group:
                continue
            group_id = str(group.get("group_id") or "")
            result.setdefault(group_id, []).append(page_id)

    return result


def _normalize_group_order(value: Any, *, valid_groups: set[str]) -> list[str]:
    if isinstance(value, list):
        return [group_id for group_id in _unique_keys(value) if group_id in valid_groups]
    if isinstance(value, dict):
        ranked = []
        for raw_group_id, rank in value.items():
            group_id = _safe_key(raw_group_id)
            if group_id not in valid_groups:
                continue
            try:
                ranked.append((int(rank), group_id))
            except (TypeError, ValueError):
                continue
        return [group_id for _, group_id in sorted(ranked)]
    return []


def _unique_keys(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = _safe_key(value)
        if key and key not in seen:
            result.append(key)
            seen.add(key)
    return result


def _safe_key(value: Any) -> str:
    text = str(value or "").strip().lower().replace(" ", "_")
    if ".." in text or "/" in text or "\\" in text:
        return ""
    return "".join(char for char in text if char.isalnum() or char in {"_", "-", ".", ":"})[:120]
