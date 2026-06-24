from __future__ import annotations

import base64
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from money_manager.config.install_paths import SYSTEM_DIR
from money_manager.config.user_paths import normalize_user_id
from money_manager.security.protection_manager import read_json, write_json_atomic

SECURITY_SCHEMA_VERSION = 1
KDF_ALGORITHM = "pbkdf2_sha256"
KDF_ITERATIONS = 600_000
KEY_BYTES = 32
NONCE_BYTES = 12

_METADATA_LOCK = threading.RLock()
_METADATA_CACHE: dict[str, tuple[int, int, dict[str, Any]]] = {}


def clear_security_metadata_cache(user_id: str | None = None) -> None:
    safe_id = normalize_user_id(user_id) if user_id else ""
    with _METADATA_LOCK:
        if safe_id:
            _METADATA_CACHE.pop(safe_id, None)
        else:
            _METADATA_CACHE.clear()


def _metadata_stat(path: Path) -> tuple[int, int]:
    try:
        stat = path.stat()
        return int(stat.st_mtime_ns), int(stat.st_size)
    except OSError:
        return 0, 0


class KeyManagementError(RuntimeError):
    pass


class EncryptionNotEnabled(KeyManagementError):
    pass


class UnlockFailed(KeyManagementError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def security_users_dir() -> Path:
    path = SYSTEM_DIR / "security" / "users"
    path.mkdir(parents=True, exist_ok=True)
    return path


def metadata_path(user_id: str) -> Path:
    return security_users_dir() / f"{normalize_user_id(user_id)}.json"


def default_metadata(user_id: str) -> dict[str, Any]:
    now = utc_now()
    return {
        "schema_version": SECURITY_SCHEMA_VERSION,
        "user_id": normalize_user_id(user_id),
        "encryption_enabled": False,
        "kdf": {
            "algorithm": KDF_ALGORITHM,
            "salt": "",
            "iterations": KDF_ITERATIONS,
        },
        "encrypted_dek": "",
        "dek_nonce": "",
        "created_at": now,
        "updated_at": now,
        "recovery_enabled": False,
        "recovery_hint": "",
    }


def load_security_metadata(user_id: str, *, create: bool = True) -> dict[str, Any]:
    safe_id = normalize_user_id(user_id)
    path = metadata_path(safe_id)
    mtime_ns, size = _metadata_stat(path)
    if size:
        with _METADATA_LOCK:
            cached = _METADATA_CACHE.get(safe_id)
            if cached and cached[0] == mtime_ns and cached[1] == size:
                return dict(cached[2])

    payload = read_json(path, None)
    if not isinstance(payload, dict):
        payload = default_metadata(safe_id)
        if create:
            write_json_atomic(path, payload)
            mtime_ns, size = _metadata_stat(path)
        with _METADATA_LOCK:
            _METADATA_CACHE[safe_id] = (mtime_ns, size, dict(payload))
        return dict(payload)

    merged = default_metadata(safe_id)
    merged.update(payload)
    kdf = dict(default_metadata(safe_id)["kdf"])
    if isinstance(payload.get("kdf"), dict):
        kdf.update(payload["kdf"])
    merged["kdf"] = kdf
    merged["user_id"] = safe_id
    if create and merged != payload:
        write_json_atomic(path, merged)
        mtime_ns, size = _metadata_stat(path)
    with _METADATA_LOCK:
        _METADATA_CACHE[safe_id] = (mtime_ns, size, dict(merged))
    return dict(merged)


def save_security_metadata(user_id: str, metadata: dict[str, Any]) -> None:
    payload = dict(metadata or {})
    payload["schema_version"] = SECURITY_SCHEMA_VERSION
    payload["user_id"] = normalize_user_id(user_id)
    payload["updated_at"] = utc_now()
    path = metadata_path(str(user_id))
    write_json_atomic(path, payload)
    mtime_ns, size = _metadata_stat(path)
    with _METADATA_LOCK:
        _METADATA_CACHE[payload["user_id"]] = (mtime_ns, size, dict(payload))


def is_encryption_enabled(user_id: str | None) -> bool:
    if not user_id:
        return False
    return bool(load_security_metadata(str(user_id), create=True).get("encryption_enabled"))


def create_security_metadata_for_user(user_id: str) -> dict[str, Any]:
    return load_security_metadata(user_id, create=True)


def generate_dek() -> bytes:
    return os.urandom(KEY_BYTES)


def derive_kek(password: str, kdf: dict[str, Any]) -> bytes:
    algorithm = str(kdf.get("algorithm") or KDF_ALGORITHM)
    if algorithm != KDF_ALGORITHM:
        raise KeyManagementError(f"Unsupported KDF algorithm: {algorithm}")
    salt_text = str(kdf.get("salt") or "")
    if not salt_text:
        raise KeyManagementError("Security metadata has no KDF salt.")
    try:
        salt = _unb64(salt_text)
    except Exception as exc:
        raise KeyManagementError("Security metadata KDF salt is invalid.") from exc
    iterations = int(kdf.get("iterations") or KDF_ITERATIONS)
    kdf_obj = PBKDF2HMAC(algorithm=hashes.SHA256(), length=KEY_BYTES, salt=salt, iterations=iterations)
    return kdf_obj.derive(str(password or "").encode("utf-8"))


def enable_encryption_metadata(user_id: str, password: str, *, dek: bytes | None = None) -> tuple[dict[str, Any], bytes]:
    safe_id = normalize_user_id(user_id)
    metadata = load_security_metadata(safe_id, create=True)
    if metadata.get("encryption_enabled"):
        return metadata, unlock_dek(safe_id, password)
    salt = os.urandom(16)
    metadata["kdf"] = {
        "algorithm": KDF_ALGORITHM,
        "salt": _b64(salt),
        "iterations": KDF_ITERATIONS,
    }
    dek_bytes = dek or generate_dek()
    kek = derive_kek(password, metadata["kdf"])
    nonce = os.urandom(NONCE_BYTES)
    encrypted_dek = AESGCM(kek).encrypt(nonce, dek_bytes, _dek_aad(safe_id))
    metadata["encrypted_dek"] = _b64(encrypted_dek)
    metadata["dek_nonce"] = _b64(nonce)
    metadata["encryption_enabled"] = True
    metadata["recovery_enabled"] = False
    metadata["recovery_hint"] = metadata.get("recovery_hint") or ""
    save_security_metadata(safe_id, metadata)
    return metadata, dek_bytes


def unlock_dek(user_id: str, password: str) -> bytes:
    safe_id = normalize_user_id(user_id)
    metadata = load_security_metadata(safe_id, create=True)
    if not metadata.get("encryption_enabled"):
        raise EncryptionNotEnabled("Encryption is not enabled for this user.")
    try:
        kek = derive_kek(password, dict(metadata.get("kdf") or {}))
        nonce = _unb64(str(metadata.get("dek_nonce") or ""))
        encrypted_dek = _unb64(str(metadata.get("encrypted_dek") or ""))
        dek = AESGCM(kek).decrypt(nonce, encrypted_dek, _dek_aad(safe_id))
    except Exception as exc:
        raise UnlockFailed("Wrong password or corrupted security metadata.") from exc
    if len(dek) != KEY_BYTES:
        raise UnlockFailed("Decrypted data key has an invalid size.")
    return dek


def rewrap_dek(user_id: str, old_password: str, new_password: str) -> dict[str, Any]:
    safe_id = normalize_user_id(user_id)
    dek = unlock_dek(safe_id, old_password)
    metadata = load_security_metadata(safe_id, create=True)
    salt = os.urandom(16)
    metadata["kdf"] = {
        "algorithm": KDF_ALGORITHM,
        "salt": _b64(salt),
        "iterations": KDF_ITERATIONS,
    }
    kek = derive_kek(new_password, metadata["kdf"])
    nonce = os.urandom(NONCE_BYTES)
    metadata["encrypted_dek"] = _b64(AESGCM(kek).encrypt(nonce, dek, _dek_aad(safe_id)))
    metadata["dek_nonce"] = _b64(nonce)
    metadata["encryption_enabled"] = True
    save_security_metadata(safe_id, metadata)
    return metadata


def _dek_aad(user_id: str) -> bytes:
    return f"money-manager-dek:{normalize_user_id(user_id)}:v1".encode("utf-8")


def _b64(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).decode("ascii")


def _unb64(payload: str) -> bytes:
    return base64.urlsafe_b64decode(payload.encode("ascii"))
