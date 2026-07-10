from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from money_manager.config.install_paths import APP_CONFIG_DIR, DATA_HOME, GLOBAL_CACHE_DIR, SYSTEM_DIR, USERS_DIR
from money_manager.config.user_paths import normalize_user_id
from money_manager.security.secure_storage import ensure_csv_secure, read_json_secure, write_json_secure
from money_manager.services._user_config import deep_merge_defaults
from money_manager.storage.data_registry import DataFileDefinition, all_definitions, definition_by_name


def resolve_definition_path(definition: DataFileDefinition, user_id: str | None = None) -> Path:
    relative = Path(definition.relative_path) if definition.relative_path else Path()
    if definition.scope == "system":
        return SYSTEM_DIR / relative
    if definition.scope == "app_config":
        return APP_CONFIG_DIR / relative
    if definition.scope == "global_cache":
        return GLOBAL_CACHE_DIR / relative
    if definition.scope == "user":
        if not user_id:
            raise RuntimeError(f"User id is required for user-scoped data file {definition.name}.")
        return USERS_DIR / normalize_user_id(user_id) / relative
    raise ValueError(f"Unknown data definition scope: {definition.scope}")


def ensure_file_definition(definition: DataFileDefinition, user_id: str | None = None) -> dict[str, Any]:
    path = resolve_definition_path(definition, user_id=user_id)
    report: dict[str, Any] = {"name": definition.name, "path": str(path), "created": False, "repaired": False, "columns_added": []}

    if definition.file_type in {"directory", "binary_folder"}:
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            report["created"] = True
        else:
            path.mkdir(parents=True, exist_ok=True)
        return report

    if definition.file_type == "csv":
        if bool((definition.metadata or {}).get("partitioned_legacy")):
            partition_folder = str((definition.metadata or {}).get("partition_folder") or "").strip()
            partition_root = path.parent / partition_folder if partition_folder else None
            report["migration_pending"] = bool(path.exists() and not (partition_root and partition_root.exists()))
            report["partitioned"] = bool(partition_root and partition_root.exists())
            report["skipped_legacy_creation"] = not path.exists()
            return report
        created, added = ensure_csv_schema(path, list(definition.csv_fields), preserve_unknown_columns=definition.preserve_unknown_columns)
        report["created"] = created
        report["repaired"] = bool(added)
        report["columns_added"] = added
        return report

    if definition.file_type == "json":
        default_payload = definition.default_content()
        if default_payload is None:
            default_payload = {"schema_version": definition.schema_version}
        existed_before = path.exists()
        repaired = ensure_json_file(path, default_payload)
        report["created"] = not existed_before
        report["repaired"] = repaired and existed_before
        return report

    return report


def ensure_system_files() -> dict[str, Any]:
    reports = [ensure_file_definition(definition) for definition in all_definitions("system")]
    return {"files": reports}


def ensure_app_config_files() -> dict[str, Any]:
    reports = [ensure_file_definition(definition) for definition in all_definitions("app_config")]
    return {"files": reports}


def ensure_user_files(user_id: str) -> dict[str, Any]:
    safe_id = normalize_user_id(user_id)
    user_dir = USERS_DIR / safe_id
    user_dir.mkdir(parents=True, exist_ok=True)
    reports = [ensure_file_definition(definition, user_id=safe_id) for definition in all_definitions("user")]
    return summarize_reports(reports)


def summarize_reports(reports: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "files": reports,
        "csv_created": [Path(item["path"]).name for item in reports if item.get("created") and Path(item["path"]).suffix == ".csv"],
        "csv_columns_added": {Path(item["path"]).name: item.get("columns_added", []) for item in reports if item.get("columns_added")},
        "json_repaired": [Path(item["path"]).name for item in reports if item.get("repaired") and Path(item["path"]).suffix == ".json"],
        "created": [item["name"] for item in reports if item.get("created")],
        "repaired": [item["name"] for item in reports if item.get("repaired")],
    }


def ensure_csv_schema(path: Path, fieldnames: list[str], *, preserve_unknown_columns: bool = True) -> tuple[bool, list[str]]:
    return ensure_csv_secure(path, fieldnames, preserve_unknown_columns=preserve_unknown_columns)

def ensure_json_file(path: Path, default_payload: Any) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = read_json_secure(path, None)
    if raw is None:
        write_json_secure(path, deepcopy(default_payload))
        return True
    if isinstance(default_payload, dict):
        repaired = deep_merge_defaults(default_payload, raw)
        if not isinstance(repaired, dict):
            repaired = deepcopy(default_payload)
    else:
        repaired = raw
    if repaired != raw:
        write_json_secure(path, repaired)
        return True
    return False

def registry_path_map(user_id: str | None = None) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for definition in all_definitions():
        try:
            result[definition.name] = resolve_definition_path(definition, user_id=user_id)
        except RuntimeError:
            continue
    return result


def data_registry_diagnostics(user_id: str | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for definition in all_definitions():
        try:
            path = resolve_definition_path(definition, user_id=user_id)
            exists = path.exists()
        except RuntimeError:
            path = Path(f"<requires user>/{definition.relative_path}")
            exists = False
        rows.append({
            "name": definition.name,
            "scope": definition.scope,
            "expected_path": str(path),
            "exists": exists,
            "file_type": definition.file_type,
            "schema_version": definition.schema_version,
            "backup_policy": definition.backup_policy,
            "cache_policy": definition.cache_policy,
            "encryption_policy": definition.encryption_policy,
            "future_encryption_policy": definition.encryption_policy,
            "sensitive_level": definition.sensitive_level,
            "encrypted_by_default": getattr(definition, "encrypted_by_default", False),
            "description": definition.description,
        })
    return rows


def definition_for_filename(filename: str) -> DataFileDefinition | None:
    normalized = filename.replace("\\", "/").strip("/")
    for definition in all_definitions("user"):
        if definition.relative_path == normalized:
            return definition
    return definition_by_name(normalized)
