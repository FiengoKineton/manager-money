from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from money_manager.config.install_paths import DATA_DIR, PROJECT_ROOT, USERS_DIR
from money_manager.config.user_paths import normalize_user_id
from money_manager.security.protection_manager import write_json_atomic
from money_manager.storage.data_registry import flat_migration_filenames


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def migrate_flat_data_to_user_folder(user_id: str, *, source_data_dir: Path | None = None) -> dict[str, Any]:
    safe_id = normalize_user_id(user_id)
    source_root = source_data_dir or DATA_DIR
    user_dir = USERS_DIR / safe_id
    user_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    skipped: list[str] = []

    for relative_name in flat_migration_filenames():
        source = source_root / relative_name
        target = user_dir / relative_name
        if source.exists() and source.is_file():
            if target.exists():
                skipped.append(relative_name)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied.append(relative_name)

    for folder_name in ("cache",):
        source_folder = source_root / folder_name
        target_folder = user_dir / folder_name
        _copy_tree_files(source_folder, target_folder, prefix=folder_name, copied=copied, skipped=skipped)

    _copy_tree_files(PROJECT_ROOT / "static" / "plots", user_dir / "plots", prefix="plots", copied=copied, skipped=skipped)
    for documents_name in ("documents", "Documents"):
        _copy_tree_files(PROJECT_ROOT / documents_name, user_dir / "documents", prefix="documents", copied=copied, skipped=skipped)

    marker = {
        "schema_version": 1,
        "migrated_at": utc_now(),
        "source": str(source_root),
        "copied": copied,
        "skipped_existing": skipped,
        "old_files_deleted": False,
    }
    write_json_atomic(user_dir / "migration_info.json", marker)
    return marker


def _copy_tree_files(source_root: Path, target_root: Path, *, prefix: str, copied: list[str], skipped: list[str]) -> None:
    if not source_root.exists() or not source_root.is_dir():
        return
    for source in source_root.rglob("*"):
        if not source.is_file():
            continue
        relative = source.relative_to(source_root)
        target = target_root / relative
        logical_name = f"{prefix}/{relative.as_posix()}"
        if target.exists():
            skipped.append(logical_name)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied.append(logical_name)
