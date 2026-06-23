from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import Any

try:
    from flask import has_request_context, session
except Exception:  # pragma: no cover
    def has_request_context() -> bool:
        return False
    session = {}  # type: ignore

from money_manager.config.user_paths import normalize_user_id
from money_manager.security.key_manager import is_encryption_enabled, unlock_dek

VAULT_SESSION_KEY = "security_vault_id"
DEFAULT_TIMEOUT_SECONDS = 8 * 60 * 60


class VaultLockedError(RuntimeError):
    pass


@dataclass
class VaultEntry:
    user_id: str
    dek: bytes
    created_at: float
    last_used_at: float


_VAULT: dict[str, VaultEntry] = {}


def unlock_user(user_id: str, password: str, *, remember_in_session: bool = True) -> str | None:
    safe_id = normalize_user_id(user_id)
    if not is_encryption_enabled(safe_id):
        clear_session_vault_id()
        return None
    dek = unlock_dek(safe_id, password)
    vault_id = secrets.token_urlsafe(32)
    now = time.time()
    _VAULT[vault_id] = VaultEntry(user_id=safe_id, dek=dek, created_at=now, last_used_at=now)
    if remember_in_session and has_request_context():
        session[VAULT_SESSION_KEY] = vault_id
    return vault_id


def current_vault_id() -> str | None:
    if not has_request_context():
        return None
    value = session.get(VAULT_SESSION_KEY)
    return str(value) if value else None


def clear_session_vault_id() -> None:
    if has_request_context():
        session.pop(VAULT_SESSION_KEY, None)


def get_dek(user_id: str | None, vault_id: str | None = None) -> bytes | None:
    safe_id = normalize_user_id(user_id) if user_id else ""
    if not safe_id or not is_encryption_enabled(safe_id):
        return None
    vault_key = vault_id or current_vault_id()
    entry = _VAULT.get(vault_key) if vault_key else None
    if not entry or entry.user_id != safe_id:
        # Non-Flask tools and migrations may unlock a user without a cookie
        # session. In that case, use the in-memory entry for that user.
        entry = None
        vault_key = None
        for candidate_id, candidate in _VAULT.items():
            if candidate.user_id == safe_id:
                entry = candidate
                vault_key = candidate_id
                break
    if not entry or entry.user_id != safe_id:
        return None
    if time.time() - entry.last_used_at > DEFAULT_TIMEOUT_SECONDS:
        lock_vault(vault_key)
        return None
    entry.last_used_at = time.time()
    return entry.dek


def require_dek(user_id: str | None, vault_id: str | None = None) -> bytes:
    dek = get_dek(user_id, vault_id=vault_id)
    if dek is None:
        raise VaultLockedError("Your encrypted Money Manager vault is locked. Log in or unlock it again.")
    return dek


def is_unlocked(user_id: str | None, vault_id: str | None = None) -> bool:
    if not user_id or not is_encryption_enabled(user_id):
        return True
    return get_dek(user_id, vault_id=vault_id) is not None


def lock_vault(vault_id: str | None = None) -> None:
    vault_key = vault_id or current_vault_id()
    if vault_key:
        _VAULT.pop(vault_key, None)
    if has_request_context():
        clear_session_vault_id()


def lock_user(user_id: str | None) -> None:
    safe_id = normalize_user_id(user_id) if user_id else ""
    for vault_id, entry in list(_VAULT.items()):
        if entry.user_id == safe_id:
            _VAULT.pop(vault_id, None)
    if has_request_context() and safe_id:
        clear_session_vault_id()


def vault_status(user_id: str | None) -> dict[str, Any]:
    enabled = is_encryption_enabled(user_id) if user_id else False
    return {
        "encryption_enabled": enabled,
        "unlocked": is_unlocked(user_id) if user_id else False,
        "vault_id_present": bool(current_vault_id()),
        "timeout_seconds": DEFAULT_TIMEOUT_SECONDS,
    }
