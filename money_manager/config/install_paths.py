from __future__ import annotations

from pathlib import Path
from typing import Any

from money_manager.config.app_home import (
    PROJECT_ROOT,
    build_install_state_payload,
    build_local_app_payload,
    ensure_app_home,
    get_app_paths,
    load_app_version,
    read_install_state,
    read_local_app,
    resolve_data_home,
    write_install_state,
)

_APP_PATHS = get_app_paths()

DATA_HOME: Path = _APP_PATHS["data_home"]
APP_CONFIG_DIR: Path = _APP_PATHS["app_config_dir"]
LOCAL_APP_JSON: Path = _APP_PATHS["local_app_json"]
INSTALL_STATE_JSON: Path = _APP_PATHS["install_state_json"]
DATA_DIR: Path = _APP_PATHS["data_dir"]
SYSTEM_DIR: Path = _APP_PATHS["system_dir"]
USERS_DIR: Path = _APP_PATHS["users_dir"]
BACKUPS_DIR: Path = _APP_PATHS["backups_dir"]
UPDATES_DIR: Path = _APP_PATHS["updates_dir"]
UPDATE_INBOX_DIR: Path = UPDATES_DIR / "inbox"
UPDATE_STAGING_DIR: Path = UPDATES_DIR / "staging"
UPDATE_INSTALLED_DIR: Path = UPDATES_DIR / "installed"
UPDATE_FAILED_DIR: Path = UPDATES_DIR / "failed"
UPDATE_ROLLBACK_DIR: Path = UPDATES_DIR / "rollback"
LOGS_DIR: Path = _APP_PATHS["logs_dir"]
GLOBAL_CACHE_DIR: Path = _APP_PATHS["cache_dir"]


def refresh_paths() -> dict[str, Path]:
    global _APP_PATHS, DATA_HOME, APP_CONFIG_DIR, LOCAL_APP_JSON, INSTALL_STATE_JSON
    global DATA_DIR, SYSTEM_DIR, USERS_DIR, BACKUPS_DIR, UPDATES_DIR, UPDATE_INBOX_DIR
    global UPDATE_STAGING_DIR, UPDATE_INSTALLED_DIR, UPDATE_FAILED_DIR, UPDATE_ROLLBACK_DIR
    global LOGS_DIR, GLOBAL_CACHE_DIR
    _APP_PATHS = get_app_paths()
    DATA_HOME = _APP_PATHS["data_home"]
    APP_CONFIG_DIR = _APP_PATHS["app_config_dir"]
    LOCAL_APP_JSON = _APP_PATHS["local_app_json"]
    INSTALL_STATE_JSON = _APP_PATHS["install_state_json"]
    DATA_DIR = _APP_PATHS["data_dir"]
    SYSTEM_DIR = _APP_PATHS["system_dir"]
    USERS_DIR = _APP_PATHS["users_dir"]
    BACKUPS_DIR = _APP_PATHS["backups_dir"]
    UPDATES_DIR = _APP_PATHS["updates_dir"]
    UPDATE_INBOX_DIR = UPDATES_DIR / "inbox"
    UPDATE_STAGING_DIR = UPDATES_DIR / "staging"
    UPDATE_INSTALLED_DIR = UPDATES_DIR / "installed"
    UPDATE_FAILED_DIR = UPDATES_DIR / "failed"
    UPDATE_ROLLBACK_DIR = UPDATES_DIR / "rollback"
    LOGS_DIR = _APP_PATHS["logs_dir"]
    GLOBAL_CACHE_DIR = _APP_PATHS["cache_dir"]
    return _APP_PATHS


def describe_install_paths() -> dict[str, str]:
    refresh_paths()
    return {key: str(value) for key, value in _APP_PATHS.items()}


def current_app_version() -> dict[str, Any]:
    return load_app_version(PROJECT_ROOT)
