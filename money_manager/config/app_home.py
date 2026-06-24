from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_NAME = "Money Manager"
APP_ID = "money_manager"
DEFAULT_DATA_HOME_NAME = "MoneyManagerData"
LOCAL_APP_SCHEMA_VERSION = 1
INSTALL_STATE_SCHEMA_VERSION = 1
DEFAULT_APP_VERSION = {
    "app_id": APP_ID,
    "version": "0.14.0",
    "data_schema_min": 1,
    "data_schema_current": 14,
    "requires_registry_version": 1,
    "release_channel": "local",
    "created_at": "",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json_file(path: Path, default: Any = None) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default
    return default


def write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, ensure_ascii=False)

    tmp = path.with_name(path.name + ".writing")
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
        return
    except PermissionError:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass

    # Fallback for Windows/antivirus cases where Python is blocked from
    # creating temporary sidecar files. This is less atomic, but prevents
    # launcher startup from failing.
    path.write_text(text, encoding="utf-8")


def launcher_config_path() -> Path | None:
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / "MoneyManagerLauncher" / "config.json"
    if os.name == "nt":
        return None
    return Path.home() / ".config" / "MoneyManagerLauncher" / "config.json"


def load_launcher_config() -> dict[str, Any]:
    path = launcher_config_path()
    payload = read_json_file(path, {}) if path else {}
    return payload if isinstance(payload, dict) else {}


def load_app_version(app_dir: Path | None = None) -> dict[str, Any]:
    path = (app_dir or PROJECT_ROOT) / "app_version.json"
    payload = read_json_file(path, None)
    if not isinstance(payload, dict):
        payload = dict(DEFAULT_APP_VERSION)
    merged = dict(DEFAULT_APP_VERSION)
    merged.update(payload)
    return merged


def repo_data_fallback_enabled() -> bool:
    return os.environ.get("MONEY_MANAGER_USE_REPO_DATA", "").strip().casefold() in {"1", "true", "yes", "on", "dev"}


def _candidate_data_home_from_local_file(path: Path) -> Path | None:
    payload = read_json_file(path, None)
    if isinstance(payload, dict) and payload.get("data_home"):
        return Path(str(payload["data_home"])).expanduser()
    return None


def resolve_data_home() -> Path:
    env_home = os.environ.get("MONEY_MANAGER_DATA_HOME")
    if env_home:
        return Path(env_home).expanduser().resolve()

    launcher_config = load_launcher_config()
    launcher_home = launcher_config.get("data_home") or launcher_config.get("data_dir_home")
    if launcher_home:
        return Path(str(launcher_home)).expanduser().resolve()

    sibling = (PROJECT_ROOT.parent / DEFAULT_DATA_HOME_NAME).resolve()
    local = sibling / "app_config" / "local_app.json"
    local_home = _candidate_data_home_from_local_file(local)
    if local_home:
        return local_home.resolve()

    if repo_data_fallback_enabled():
        # Explicit development-only fallback. Normal distributed runs keep money
        # data outside the code folder.
        return (PROJECT_ROOT / "data").resolve()

    return sibling


def build_local_app_payload(data_home: Path | None = None) -> dict[str, Any]:
    data_home = (data_home or resolve_data_home()).resolve()
    data_dir = data_home / "data"
    now = utc_now()
    existing = read_json_file(data_home / "app_config" / "local_app.json", {})
    created_at = existing.get("created_at") if isinstance(existing, dict) else ""
    payload = {
        "schema_version": LOCAL_APP_SCHEMA_VERSION,
        "app_name": APP_NAME,
        "app_dir": str(PROJECT_ROOT),
        "data_home": str(data_home),
        "data_dir": str(data_dir),
        "system_dir": str(data_dir / "_system"),
        "users_dir": str(data_dir / "users"),
        "updates_dir": str(data_home / "updates"),
        "backups_dir": str(data_home / "backups"),
        "logs_dir": str(data_home / "logs"),
        "cache_dir": str(data_home / "cache"),
        "update_source": {
            "mode": "local_folder",
            "local_inbox": str(data_home / "updates" / "inbox"),
            "remote_manifest_url": "",
        },
        "auto_apply_updates": False,
        "created_at": created_at or now,
        "updated_at": now,
    }
    if isinstance(existing, dict):
        update_source = existing.get("update_source") if isinstance(existing.get("update_source"), dict) else {}
        if existing.get("auto_apply_updates") is not None:
            payload["auto_apply_updates"] = bool(existing.get("auto_apply_updates"))
        if update_source.get("remote_manifest_url"):
            payload["update_source"]["remote_manifest_url"] = str(update_source.get("remote_manifest_url"))
    return payload


def build_install_state_payload(data_home: Path | None = None) -> dict[str, Any]:
    data_home = (data_home or resolve_data_home()).resolve()
    app_version = load_app_version()
    existing = read_json_file(data_home / "app_config" / "install_state.json", {})
    payload = {
        "schema_version": INSTALL_STATE_SCHEMA_VERSION,
        "installed_version": str(app_version.get("version") or "0.12.0"),
        "previous_version": "",
        "current_app_dir": str(PROJECT_ROOT),
        "data_home": str(data_home),
        "last_successful_update_at": "",
        "last_failed_update_at": "",
        "rollback_available": False,
        "rollback_dir": "",
        "data_schema_version": int(app_version.get("data_schema_current") or 12),
        "pending_update": {},
        "history": [],
    }
    if isinstance(existing, dict):
        for key, value in existing.items():
            if key in {"schema_version", "current_app_dir", "data_home"}:
                continue
            payload[key] = value
    return payload


def ensure_external_data_migration(data_home: Path, install_state: dict[str, Any]) -> bool:
    if repo_data_fallback_enabled():
        return False
    repo_data = PROJECT_ROOT / "data"
    target_data = data_home / "data"
    if not repo_data.exists() or not repo_data.is_dir():
        return False

    target_has_data = target_data.exists() and any(item.is_file() for item in target_data.rglob("*"))
    if target_has_data:
        return False

    target_data.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(repo_data, target_data, dirs_exist_ok=True)
    note = {
        "event": "external_data_migration",
        "at": utc_now(),
        "source": str(repo_data),
        "target": str(target_data),
        "old_repo_data_deleted": False,
        "note": "Existing repo/data was copied to the external data folder. The original folder was left untouched.",
    }
    history = install_state.setdefault("history", [])
    if isinstance(history, list):
        history.append(note)
    return True


def ensure_app_home(data_home: Path | None = None) -> dict[str, Path]:
    data_home = (data_home or resolve_data_home()).resolve()
    app_config_dir = data_home / "app_config"
    local_app_path = app_config_dir / "local_app.json"
    install_state_path = app_config_dir / "install_state.json"

    local_payload = build_local_app_payload(data_home)
    install_state = build_install_state_payload(data_home)

    # Create directories before writing config files.
    for folder in (
        app_config_dir,
        data_home / "data" / "_system",
        data_home / "data" / "users",
        data_home / "backups",
        data_home / "updates" / "inbox",
        data_home / "updates" / "staging",
        data_home / "updates" / "installed",
        data_home / "updates" / "failed",
        data_home / "updates" / "rollback",
        data_home / "logs",
        data_home / "cache",
    ):
        folder.mkdir(parents=True, exist_ok=True)

    ensure_external_data_migration(data_home, install_state)
    write_json_atomic(local_app_path, local_payload)
    write_json_atomic(install_state_path, install_state)
    return {
        "project_root": PROJECT_ROOT,
        "data_home": data_home,
        "app_config_dir": app_config_dir,
        "local_app_json": local_app_path,
        "install_state_json": install_state_path,
        "data_dir": data_home / "data",
        "system_dir": data_home / "data" / "_system",
        "users_dir": data_home / "data" / "users",
        "backups_dir": data_home / "backups",
        "updates_dir": data_home / "updates",
        "logs_dir": data_home / "logs",
        "cache_dir": data_home / "cache",
    }


def get_app_paths() -> dict[str, Path]:
    return ensure_app_home()


def read_local_app() -> dict[str, Any]:
    paths = ensure_app_home()
    payload = read_json_file(paths["local_app_json"], {})
    return payload if isinstance(payload, dict) else {}


def read_install_state() -> dict[str, Any]:
    paths = ensure_app_home()
    payload = read_json_file(paths["install_state_json"], {})
    return payload if isinstance(payload, dict) else {}


def write_install_state(payload: dict[str, Any]) -> None:
    paths = ensure_app_home()
    payload = dict(payload)
    payload["schema_version"] = INSTALL_STATE_SCHEMA_VERSION
    payload["current_app_dir"] = str(PROJECT_ROOT)
    payload["data_home"] = str(paths["data_home"])
    write_json_atomic(paths["install_state_json"], payload)
