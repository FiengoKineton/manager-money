from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping, Sequence

from money_manager.config.navigation_registry import (
    DEFAULT_NAVIGATION as NAVIGATION_REGISTRY,
    navigation_registry,
    registry_group_ids,
    registry_page_ids,
    registry_subgroup_ids,
)
from money_manager.config.user_defaults import DEFAULT_NAVIGATION
from money_manager.services._user_config import load_user_config, save_user_config

NAVIGATION_FILE = "navigation.json"
PROTECTED_PAGE_IDS = {"profile", "logout"}


def load_navigation_config(user_id: str | None = None) -> dict[str, Any]:
    return validate_navigation_config(load_user_config(NAVIGATION_FILE, user_id=user_id))


def save_navigation_config(config: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    return save_user_config(NAVIGATION_FILE, validate_navigation_config(config), user_id=user_id)


def validate_navigation_config(config: Mapping[str, Any] | None) -> dict[str, Any]:
    """Clean stale navigation preferences against the current grouped registry."""
    incoming = dict(config or {})
    valid_pages = registry_page_ids()
    valid_groups = registry_group_ids()
    valid_subgroups = registry_subgroup_ids()
    valid_containers = _registry_container_ids()

    hidden_pages = [page_id for page_id in _unique_keys(incoming.get("hidden_pages", [])) if page_id in valid_pages]
    hidden_pages = [page_id for page_id in hidden_pages if page_id not in PROTECTED_PAGE_IDS]

    custom_order = _normalize_custom_order(
        incoming.get("custom_order", {}),
        valid_containers=valid_containers,
        valid_pages=valid_pages,
    )
    group_order = _normalize_order(incoming.get("group_order", []), valid_ids=valid_groups)
    subgroup_order = _normalize_subgroup_order(incoming.get("subgroup_order", {}), valid_groups=valid_groups, valid_subgroups=valid_subgroups)
    collapsed_groups = [group_id for group_id in _unique_keys(incoming.get("collapsed_groups", [])) if group_id in valid_groups]
    expanded_groups = [group_id for group_id in _unique_keys(incoming.get("expanded_groups", [])) if group_id in valid_groups and group_id not in collapsed_groups]
    collapsed_subgroups = [
        subgroup_id
        for subgroup_id in _unique_keys(incoming.get("collapsed_subgroups", []))
        if subgroup_id in valid_subgroups
    ]

    expanded_subgroups = [
        subgroup_id
        for subgroup_id in _unique_keys(incoming.get("expanded_subgroups", []))
        if subgroup_id in valid_subgroups and subgroup_id not in collapsed_subgroups
    ]

    return {
        "schema_version": max(2, int(incoming.get("schema_version") or DEFAULT_NAVIGATION.get("schema_version") or 2)),
        "hidden_pages": hidden_pages,
        "custom_order": custom_order,
        "group_order": group_order,
        "subgroup_order": subgroup_order,
        "collapsed_groups": collapsed_groups,
        "expanded_groups": expanded_groups,
        "collapsed_subgroups": collapsed_subgroups,
        "expanded_subgroups": expanded_subgroups,
    }


def get_effective_navigation(
    *,
    include_hidden: bool = False,
    current_endpoint: str | None = None,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return the current sidebar groups, subgroups, pages, and user preferences."""
    config = load_navigation_config(user_id=user_id)
    hidden = set(config.get("hidden_pages", []))
    collapsed_groups = set(config.get("collapsed_groups", []))
    expanded_groups = set(config.get("expanded_groups", []))
    collapsed_subgroups = set(config.get("collapsed_subgroups", []))
    expanded_subgroups = set(config.get("expanded_subgroups", []))
    endpoint = str(current_endpoint or "")

    effective_groups: list[dict[str, Any]] = []
    groups = _ordered_records(navigation_registry(), config.get("group_order", []), id_field="group_id")

    for group in groups:
        group_id = str(group.get("group_id") or "")
        direct_items = _effective_items(
            group.get("items", []),
            order=config.get("custom_order", {}).get(group_id, []),
            hidden=hidden,
            include_hidden=include_hidden,
            current_endpoint=endpoint,
        )

        subgroup_order = config.get("subgroup_order", {}).get(group_id, [])
        ordered_subgroups = _ordered_records(group.get("subgroups", []), subgroup_order, id_field="subgroup_id")
        effective_subgroups: list[dict[str, Any]] = []
        for subgroup in ordered_subgroups:
            subgroup_id = str(subgroup.get("subgroup_id") or "")
            items = _effective_items(
                subgroup.get("items", []),
                order=config.get("custom_order", {}).get(subgroup_id, []),
                hidden=hidden,
                include_hidden=include_hidden,
                current_endpoint=endpoint,
            )
            if not items and not include_hidden:
                continue
            subgroup_active = any(bool(item.get("is_active")) for item in items)
            clean_subgroup = deepcopy(subgroup)
            clean_subgroup["items"] = items
            clean_subgroup["is_active"] = subgroup_active
            clean_subgroup["is_collapsed"] = subgroup_id in collapsed_subgroups
            clean_subgroup["is_open"] = subgroup_active or subgroup_id in expanded_subgroups or (
                bool(subgroup.get("default_open", False)) and subgroup_id not in collapsed_subgroups
            )
            effective_subgroups.append(clean_subgroup)

        if not direct_items and not effective_subgroups and not include_hidden:
            continue

        group_active = any(bool(item.get("is_active")) for item in direct_items) or any(
            bool(subgroup.get("is_active")) for subgroup in effective_subgroups
        )
        clean_group = deepcopy(group)
        clean_group["items"] = direct_items
        clean_group["subgroups"] = effective_subgroups
        clean_group["is_active"] = group_active
        clean_group["is_collapsed"] = group_id in collapsed_groups
        clean_group["is_open"] = group_active or group_id in expanded_groups or (
            bool(group.get("default_open", False)) and group_id not in collapsed_groups
        )
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
    return show_page(page_id, user_id=user_id)


def move_page(
    page_id: str,
    direction: str | None = None,
    target_index: int | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    key = _safe_key(page_id)
    found = _find_container_for_page(key)
    if not found:
        return load_navigation_config(user_id=user_id)

    container_id, items = found
    config = load_navigation_config(user_id=user_id)
    current_order = [
        str(item.get("page_id") or "")
        for item in _ordered_records(items, config.get("custom_order", {}).get(container_id, []), id_field="page_id")
    ]
    _move_key(current_order, key, direction=direction, target_index=target_index)
    config.setdefault("custom_order", {})[container_id] = current_order
    return save_navigation_config(config, user_id=user_id)


def move_group(
    group_id: str,
    direction: str | None = None,
    target_index: int | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    key = _safe_key(group_id)
    if key not in registry_group_ids():
        return load_navigation_config(user_id=user_id)
    config = load_navigation_config(user_id=user_id)
    current_order = [
        str(group.get("group_id") or "")
        for group in _ordered_records(navigation_registry(), config.get("group_order", []), id_field="group_id")
    ]
    _move_key(current_order, key, direction=direction, target_index=target_index)
    config["group_order"] = current_order
    return save_navigation_config(config, user_id=user_id)


def move_subgroup(
    group_id: str,
    subgroup_id: str,
    direction: str | None = None,
    target_index: int | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    group_key = _safe_key(group_id)
    subgroup_key = _safe_key(subgroup_id)
    group = _find_group(group_key)
    if not group or subgroup_key not in {str(item.get("subgroup_id") or "") for item in group.get("subgroups", [])}:
        return load_navigation_config(user_id=user_id)
    config = load_navigation_config(user_id=user_id)
    current_order = [
        str(item.get("subgroup_id") or "")
        for item in _ordered_records(
            group.get("subgroups", []),
            config.get("subgroup_order", {}).get(group_key, []),
            id_field="subgroup_id",
        )
    ]
    _move_key(current_order, subgroup_key, direction=direction, target_index=target_index)
    config.setdefault("subgroup_order", {})[group_key] = current_order
    return save_navigation_config(config, user_id=user_id)


def restore_default_navigation(user_id: str | None = None) -> dict[str, Any]:
    return save_navigation_config(deepcopy(DEFAULT_NAVIGATION), user_id=user_id)


def set_group_collapsed(group_id: str, collapsed: bool, user_id: str | None = None) -> dict[str, Any]:
    key = _safe_key(group_id)
    config = load_navigation_config(user_id=user_id)
    if key not in registry_group_ids():
        return config
    config["collapsed_groups"] = _toggle_key(config.get("collapsed_groups", []), key, collapsed)
    config["expanded_groups"] = _toggle_key(config.get("expanded_groups", []), key, not collapsed)
    return save_navigation_config(config, user_id=user_id)


def set_subgroup_collapsed(subgroup_id: str, collapsed: bool, user_id: str | None = None) -> dict[str, Any]:
    key = _safe_key(subgroup_id)
    config = load_navigation_config(user_id=user_id)
    if key not in registry_subgroup_ids():
        return config
    config["collapsed_subgroups"] = _toggle_key(config.get("collapsed_subgroups", []), key, collapsed)
    config["expanded_subgroups"] = _toggle_key(config.get("expanded_subgroups", []), key, not collapsed)
    return save_navigation_config(config, user_id=user_id)


def collapse_group(group_id: str, user_id: str | None = None) -> dict[str, Any]:
    return set_group_collapsed(group_id, True, user_id=user_id)


def expand_group(group_id: str, user_id: str | None = None) -> dict[str, Any]:
    return set_group_collapsed(group_id, False, user_id=user_id)


def set_custom_order(order: Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    config = load_navigation_config(user_id=user_id)
    config["custom_order"] = _normalize_custom_order(
        order,
        valid_containers=_registry_container_ids(),
        valid_pages=registry_page_ids(),
    )
    return save_navigation_config(config, user_id=user_id)


def set_group_order(order: Sequence[Any] | Mapping[str, Any], user_id: str | None = None) -> dict[str, Any]:
    config = load_navigation_config(user_id=user_id)
    config["group_order"] = _normalize_order(order, valid_ids=registry_group_ids())
    return save_navigation_config(config, user_id=user_id)


def ensure_navigation_config(user_id: str | None = None) -> dict[str, Any]:
    return load_navigation_config(user_id=user_id)


def navigation_registry_structure() -> list[dict[str, Any]]:
    return deepcopy(NAVIGATION_REGISTRY)


def _effective_items(
    items: Sequence[Mapping[str, Any]],
    *,
    order: Sequence[str],
    hidden: set[str],
    include_hidden: bool,
    current_endpoint: str,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in _ordered_records(items, order, id_field="page_id"):
        page_id = str(item.get("page_id") or "")
        is_hidden = page_id in hidden or not bool(item.get("default_visible", True))
        if is_hidden and not include_hidden:
            continue
        active_endpoints = [str(value) for value in item.get("active_endpoints", []) if value]
        if not active_endpoints:
            active_endpoints = [str(item.get("endpoint") or "")]
        clean_item = deepcopy(dict(item))
        clean_item["is_visible"] = not is_hidden
        clean_item["is_hidden"] = is_hidden
        clean_item["is_active"] = current_endpoint in active_endpoints
        clean_item["can_hide"] = page_id not in PROTECTED_PAGE_IDS
        clean_item["active_endpoints"] = active_endpoints
        result.append(clean_item)
    return result


def _ordered_records(records: Sequence[Mapping[str, Any]], custom_order: Sequence[str], *, id_field: str) -> list[dict[str, Any]]:
    rows = [deepcopy(dict(item)) for item in records]
    by_id = {str(item.get(id_field) or ""): item for item in rows}
    ordered: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_id in custom_order or []:
        key = _safe_key(raw_id)
        if key in by_id and key not in seen:
            ordered.append(by_id[key])
            seen.add(key)
    leftovers = [item for item in rows if str(item.get(id_field) or "") not in seen]
    leftovers.sort(key=lambda item: (int(item.get("default_order") or 0), str(item.get("label") or "")))
    return ordered + leftovers


def _find_group(group_id: str) -> dict[str, Any] | None:
    for group in navigation_registry():
        if str(group.get("group_id") or "") == group_id:
            return group
    return None


def _find_container_for_page(page_id: str) -> tuple[str, list[dict[str, Any]]] | None:
    for group in navigation_registry():
        group_id = str(group.get("group_id") or "")
        direct_items = list(group.get("items", []))
        if any(str(item.get("page_id") or "") == page_id for item in direct_items):
            return group_id, direct_items
        for subgroup in group.get("subgroups", []):
            subgroup_id = str(subgroup.get("subgroup_id") or "")
            items = list(subgroup.get("items", []))
            if any(str(item.get("page_id") or "") == page_id for item in items):
                return subgroup_id, items
    return None


def _registry_container_ids() -> set[str]:
    result = registry_group_ids()
    result.update(registry_subgroup_ids())
    return result


def _move_key(order: list[str], key: str, *, direction: str | None, target_index: int | None) -> None:
    if key not in order:
        return
    old_index = order.index(key)
    if target_index is not None:
        new_index = max(0, min(int(target_index), len(order) - 1))
    else:
        direction_key = str(direction or "").strip().casefold()
        step = -1 if direction_key == "up" else 1 if direction_key == "down" else 0
        new_index = max(0, min(old_index + step, len(order) - 1))
    if new_index != old_index:
        order.insert(new_index, order.pop(old_index))


def _toggle_key(values: Sequence[Any], key: str, enabled: bool) -> list[str]:
    result = [item for item in _unique_keys(list(values or [])) if item != key]
    if enabled:
        result.append(key)
    return result


def _normalize_custom_order(value: Any, *, valid_containers: set[str], valid_pages: set[str]) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, list[str]] = {}
    for raw_container_id, raw_order in value.items():
        container_id = _safe_key(raw_container_id)
        if container_id not in valid_containers:
            continue
        page_order: list[str] = []
        if isinstance(raw_order, list):
            page_order = _unique_keys(raw_order)
        elif isinstance(raw_order, dict):
            ranked: list[tuple[int, str]] = []
            for raw_page_id, rank in raw_order.items():
                page_id = _safe_key(raw_page_id)
                try:
                    ranked.append((int(rank), page_id))
                except (TypeError, ValueError):
                    continue
            page_order = [page_id for _, page_id in sorted(ranked)]
        page_order = [page_id for page_id in page_order if page_id in valid_pages]
        if page_order:
            result[container_id] = page_order

    # Backward compatibility: old files used group IDs for all pages. Move each
    # page to its current subgroup/direct-item container without losing order.
    for raw_container_id, raw_order in value.items():
        if _safe_key(raw_container_id) not in registry_group_ids() or not isinstance(raw_order, list):
            continue
        for page_id in _unique_keys(raw_order):
            found = _find_container_for_page(page_id)
            if not found:
                continue
            container_id, _ = found
            result.setdefault(container_id, [])
            if page_id not in result[container_id]:
                result[container_id].append(page_id)
    return result


def _normalize_subgroup_order(value: Any, *, valid_groups: set[str], valid_subgroups: set[str]) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, list[str]] = {}
    for raw_group_id, raw_order in value.items():
        group_id = _safe_key(raw_group_id)
        if group_id not in valid_groups:
            continue
        order = [subgroup_id for subgroup_id in _normalize_order(raw_order, valid_ids=valid_subgroups)]
        group = _find_group(group_id)
        group_subgroups = {str(item.get("subgroup_id") or "") for item in (group or {}).get("subgroups", [])}
        order = [subgroup_id for subgroup_id in order if subgroup_id in group_subgroups]
        if order:
            result[group_id] = order
    return result


def _normalize_order(value: Any, *, valid_ids: set[str]) -> list[str]:
    if isinstance(value, list):
        return [key for key in _unique_keys(value) if key in valid_ids]
    if isinstance(value, dict):
        ranked: list[tuple[int, str]] = []
        for raw_key, rank in value.items():
            key = _safe_key(raw_key)
            if key not in valid_ids:
                continue
            try:
                ranked.append((int(rank), key))
            except (TypeError, ValueError):
                continue
        return [key for _, key in sorted(ranked)]
    return []


def _unique_keys(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    result: list[str] = []
    for value in values:
        key = _safe_key(value)
        if key and key not in result:
            result.append(key)
    return result


def _safe_key(value: Any) -> str:
    return str(value or "").strip()
