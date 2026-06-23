from __future__ import annotations

import compileall
import hashlib
import json
import os
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from money_manager.config.install_paths import (
    DATA_HOME,
    PROJECT_ROOT,
    UPDATE_FAILED_DIR,
    UPDATE_INBOX_DIR,
    UPDATE_INSTALLED_DIR,
    UPDATE_ROLLBACK_DIR,
    UPDATE_STAGING_DIR,
    GLOBAL_CACHE_DIR,
    current_app_version,
)
from money_manager.config.app_home import read_install_state, write_install_state

UPDATE_MANIFEST = "update_manifest.json"
APP_FOLDER = "app"
EXCLUDED_CODE_NAMES = {".venv", "venv", "__pycache__", ".git", "data", "MoneyManagerData"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}


class UpdateValidationError(ValueError):
    """Raised when an update ZIP is missing required metadata or is incompatible."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _version_tuple(value: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in str(value or "").replace("-", ".").split("."):
        digits = "".join(char for char in chunk if char.isdigit())
        if digits:
            parts.append(int(digits))
        else:
            parts.append(0)
    return tuple(parts or [0])


def _version_gte(left: str, right: str) -> bool:
    return _version_tuple(left) >= _version_tuple(right)


def _version_lte(left: str, right: str) -> bool:
    return _version_tuple(left) <= _version_tuple(right)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_manifest_from_zip(path: Path) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(path, "r") as archive:
            if UPDATE_MANIFEST not in archive.namelist():
                raise UpdateValidationError("Missing update_manifest.json.")
            payload = json.loads(archive.read(UPDATE_MANIFEST).decode("utf-8"))
            if not isinstance(payload, dict):
                raise UpdateValidationError("update_manifest.json must contain a JSON object.")
            return payload
    except zipfile.BadZipFile as exc:
        raise UpdateValidationError("Update package is not a valid ZIP file.") from exc
    except json.JSONDecodeError as exc:
        raise UpdateValidationError("update_manifest.json is not valid JSON.") from exc


def validate_update_package(path: Path) -> dict[str, Any]:
    manifest = read_manifest_from_zip(path)
    app_version = current_app_version()
    install_state = read_install_state()
    current_version = str(app_version.get("version") or install_state.get("installed_version") or "0.0.0")
    current_data_schema = int(install_state.get("data_schema_version") or app_version.get("data_schema_current") or 0)

    if manifest.get("app_id") != app_version.get("app_id", "money_manager"):
        raise UpdateValidationError("This update package is for a different app.")
    if int(manifest.get("schema_version") or 0) != 1:
        raise UpdateValidationError("Unsupported update manifest schema version.")
    target_version = str(manifest.get("version") or "").strip()
    if not target_version:
        raise UpdateValidationError("Update manifest has no target version.")
    min_source = str(manifest.get("min_source_version") or "").strip()
    max_source = str(manifest.get("max_source_version") or "").strip()
    if min_source and not _version_gte(current_version, min_source):
        raise UpdateValidationError(f"Current version {current_version} is older than required source version {min_source}.")
    if max_source and not _version_lte(current_version, max_source):
        raise UpdateValidationError(f"Current version {current_version} is newer than max supported source version {max_source}.")
    data_schema_min = int(manifest.get("data_schema_min") or 0)
    if data_schema_min and current_data_schema < data_schema_min:
        raise UpdateValidationError(f"Current data schema {current_data_schema} is older than required schema {data_schema_min}.")

    expected_checksum = str(manifest.get("checksum_sha256") or "").strip().lower()
    if expected_checksum:
        actual = sha256_file(path)
        if expected_checksum != actual:
            raise UpdateValidationError("Update package checksum does not match checksum_sha256.")

    with zipfile.ZipFile(path, "r") as archive:
        names = archive.namelist()
        if not any(name.startswith(f"{APP_FOLDER}/") for name in names):
            raise UpdateValidationError("Update package must contain an app/ folder.")
        unsafe = [name for name in names if name.startswith("/") or ".." in Path(name).parts or "\\" in name]
        if unsafe:
            raise UpdateValidationError(f"Update package contains unsafe paths: {unsafe[:3]}")

    return {
        "ok": True,
        "path": str(path),
        "filename": path.name,
        "manifest": manifest,
        "current_version": current_version,
        "current_data_schema": current_data_schema,
        "package_sha256": sha256_file(path),
    }


def list_update_packages() -> list[dict[str, Any]]:
    UPDATE_INBOX_DIR.mkdir(parents=True, exist_ok=True)
    packages: list[dict[str, Any]] = []
    for path in sorted(UPDATE_INBOX_DIR.glob("*.zip")):
        try:
            info = validate_update_package(path)
            info["valid"] = True
        except UpdateValidationError as exc:
            manifest = {}
            try:
                manifest = read_manifest_from_zip(path)
            except Exception:
                pass
            info = {"valid": False, "path": str(path), "filename": path.name, "manifest": manifest, "error": str(exc)}
        packages.append(info)
    return packages


def stage_update_package(package_filename: str) -> dict[str, Any]:
    safe_name = Path(package_filename).name
    package_path = UPDATE_INBOX_DIR / safe_name
    if not package_path.exists():
        raise UpdateValidationError("Update package was not found in the update inbox.")
    validation = validate_update_package(package_path)
    manifest = validation["manifest"]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    stage_dir = UPDATE_STAGING_DIR / f"{manifest.get('version')}_{stamp}"
    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    stage_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(package_path, "r") as archive:
        archive.extractall(stage_dir)

    app_source = stage_dir / APP_FOLDER
    compile_ok = compileall.compile_dir(str(app_source / "money_manager"), quiet=1) if (app_source / "money_manager").exists() else True
    if not compile_ok:
        shutil.move(str(stage_dir), str(UPDATE_FAILED_DIR / stage_dir.name))
        raise UpdateValidationError("Staged update failed Python compile check.")

    install_state = read_install_state()
    install_state["pending_update"] = {
        "type": "code_update",
        "status": "staged",
        "apply_on_restart": True,
        "staged_at": utc_now(),
        "package": str(package_path),
        "staging_dir": str(stage_dir),
        "manifest": manifest,
        "package_sha256": validation["package_sha256"],
    }
    history = install_state.setdefault("history", [])
    if isinstance(history, list):
        history.append({"event": "update_staged", "at": utc_now(), "version": manifest.get("version"), "package": safe_name})
    write_install_state(install_state)
    return {"ok": True, "staging_dir": str(stage_dir), "manifest": manifest, "restart_required": True}


def rollback_status() -> dict[str, Any]:
    install_state = read_install_state()
    rollback_dir = str(install_state.get("rollback_dir") or "")
    return {
        "available": bool(install_state.get("rollback_available") and rollback_dir and Path(rollback_dir).exists()),
        "rollback_dir": rollback_dir,
        "previous_version": install_state.get("previous_version", ""),
    }


def request_rollback() -> dict[str, Any]:
    status = rollback_status()
    if not status["available"]:
        raise UpdateValidationError("No rollback folder is available.")
    install_state = read_install_state()
    install_state["pending_update"] = {
        "type": "rollback",
        "status": "staged",
        "apply_on_restart": True,
        "staged_at": utc_now(),
        "rollback_dir": status["rollback_dir"],
        "warning": "Rollback restores code only. If data was migrated forward, restore a matching data backup manually before using old code.",
    }
    history = install_state.setdefault("history", [])
    if isinstance(history, list):
        history.append({"event": "rollback_requested", "at": utc_now(), "rollback_dir": status["rollback_dir"]})
    write_install_state(install_state)
    return {"ok": True, "restart_required": True, **status}


def update_status() -> dict[str, Any]:
    app_version = current_app_version()
    install_state = read_install_state()
    return {
        "current_version": app_version.get("version", install_state.get("installed_version", "")),
        "app_id": app_version.get("app_id", "money_manager"),
        "data_schema_current": app_version.get("data_schema_current", install_state.get("data_schema_version", "")),
        "data_home": str(DATA_HOME),
        "app_dir": str(PROJECT_ROOT),
        "update_inbox": str(UPDATE_INBOX_DIR),
        "pending_update": install_state.get("pending_update") if isinstance(install_state.get("pending_update"), dict) else {},
        "rollback": rollback_status(),
        "history": install_state.get("history", []),
        "install_state": install_state,
    }


def apply_pending_update_from_launcher() -> dict[str, Any]:
    install_state = read_install_state()
    pending = install_state.get("pending_update") if isinstance(install_state.get("pending_update"), dict) else {}
    if not pending or not pending.get("apply_on_restart"):
        return {"ok": True, "applied": False, "message": "No staged update."}

    if pending.get("type") == "rollback":
        return _apply_rollback(pending, install_state)
    return _apply_code_update(pending, install_state)


def _apply_code_update(pending: dict[str, Any], install_state: dict[str, Any]) -> dict[str, Any]:
    stage_dir = Path(str(pending.get("staging_dir") or ""))
    app_source = stage_dir / APP_FOLDER
    manifest = pending.get("manifest") if isinstance(pending.get("manifest"), dict) else {}
    if not app_source.exists():
        raise UpdateValidationError("Staged app folder is missing.")
    if not compileall.compile_dir(str(app_source / "money_manager"), quiet=1):
        raise UpdateValidationError("Staged update failed compile check before apply.")

    current_version = str(current_app_version().get("version") or install_state.get("installed_version") or "")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    rollback_dir = UPDATE_ROLLBACK_DIR / f"{current_version or 'unknown'}_{stamp}"
    _copy_code_tree(PROJECT_ROOT, rollback_dir)

    try:
        _overlay_code_tree(app_source, PROJECT_ROOT)
        if not compileall.compile_dir(str(PROJECT_ROOT / "money_manager"), quiet=1):
            raise UpdateValidationError("Updated code failed compile check after apply.")
    except Exception:
        _overlay_code_tree(rollback_dir, PROJECT_ROOT)
        install_state["last_failed_update_at"] = utc_now()
        install_state["pending_update"] = {}
        history = install_state.setdefault("history", [])
        if isinstance(history, list):
            history.append({"event": "update_failed_rolled_back", "at": utc_now(), "target_version": manifest.get("version")})
        write_install_state(install_state)
        raise

    install_state["previous_version"] = current_version
    install_state["installed_version"] = str(manifest.get("version") or current_version)
    install_state["data_schema_version"] = int(manifest.get("data_schema_target") or install_state.get("data_schema_version") or 0)
    install_state["last_successful_update_at"] = utc_now()
    install_state["rollback_available"] = True
    install_state["rollback_dir"] = str(rollback_dir)
    install_state["pending_update"] = {}
    history = install_state.setdefault("history", [])
    cache_report = _invalidate_cache_after_code_change("app_update")
    install_state["cache_invalidation"] = cache_report
    if isinstance(history, list):
        history.append({"event": "update_applied", "at": utc_now(), "from": current_version, "to": install_state["installed_version"], "rollback_dir": str(rollback_dir)})
        history.append({"event": "cache_invalidated", "at": cache_report["at"], "reason": cache_report["reason"], "cache_root": cache_report["cache_root"]})
    write_install_state(install_state)
    try:
        shutil.move(str(stage_dir), str(UPDATE_INSTALLED_DIR / stage_dir.name))
    except Exception:
        pass
    return {"ok": True, "applied": True, "version": install_state["installed_version"], "rollback_dir": str(rollback_dir)}


def _apply_rollback(pending: dict[str, Any], install_state: dict[str, Any]) -> dict[str, Any]:
    rollback_dir = Path(str(pending.get("rollback_dir") or install_state.get("rollback_dir") or ""))
    if not rollback_dir.exists():
        raise UpdateValidationError("Rollback directory is missing.")
    current_version = str(current_app_version().get("version") or install_state.get("installed_version") or "")
    _overlay_code_tree(rollback_dir, PROJECT_ROOT)
    if not compileall.compile_dir(str(PROJECT_ROOT / "money_manager"), quiet=1):
        raise UpdateValidationError("Rollback code failed compile check.")
    install_state["installed_version"] = install_state.get("previous_version") or current_version
    install_state["previous_version"] = current_version
    install_state["rollback_available"] = False
    install_state["pending_update"] = {}
    history = install_state.setdefault("history", [])
    cache_report = _invalidate_cache_after_code_change("rollback")
    install_state["cache_invalidation"] = cache_report
    if isinstance(history, list):
        history.append({"event": "rollback_applied", "at": utc_now(), "from": current_version, "to": install_state["installed_version"]})
        history.append({"event": "cache_invalidated", "at": cache_report["at"], "reason": cache_report["reason"], "cache_root": cache_report["cache_root"]})
    write_install_state(install_state)
    return {"ok": True, "applied": True, "rollback": True, "version": install_state["installed_version"]}



def _invalidate_cache_after_code_change(reason: str) -> dict[str, Any]:
    cache_root = GLOBAL_CACHE_DIR / "users"
    removed = False
    try:
        if cache_root.exists():
            shutil.rmtree(cache_root)
            removed = True
        cache_root.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return {"at": utc_now(), "reason": reason, "cache_root": str(cache_root), "removed": removed, "error": str(exc)}
    return {"at": utc_now(), "reason": reason, "cache_root": str(cache_root), "removed": removed}

def _copy_code_tree(source: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        if _should_skip(item):
            continue
        destination = target / item.name
        if item.is_dir():
            shutil.copytree(item, destination, ignore=_ignore_code_artifacts)
        elif item.is_file():
            shutil.copy2(item, destination)


def _overlay_code_tree(source: Path, target: Path) -> None:
    for item in source.iterdir():
        if _should_skip(item):
            continue
        destination = target / item.name
        if item.is_dir():
            if destination.exists():
                shutil.rmtree(destination)
            shutil.copytree(item, destination, ignore=_ignore_code_artifacts)
        elif item.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                destination.unlink()
            shutil.copy2(item, destination)


def _should_skip(path: Path) -> bool:
    if path.name in EXCLUDED_CODE_NAMES:
        return True
    if path.suffix in EXCLUDED_SUFFIXES:
        return True
    if path.name.endswith(".zip") and path.parent == PROJECT_ROOT:
        return True
    return False


def _ignore_code_artifacts(directory: str, names: list[str]) -> set[str]:
    ignored: set[str] = set()
    for name in names:
        if name in EXCLUDED_CODE_NAMES or Path(name).suffix in EXCLUDED_SUFFIXES:
            ignored.add(name)
    return ignored
