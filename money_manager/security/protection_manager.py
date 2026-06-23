from __future__ import annotations

import json
import os
import secrets
import hashlib
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

try:
    from werkzeug.security import check_password_hash, generate_password_hash
except Exception:  # pragma: no cover - only used if Werkzeug is unavailable.
    check_password_hash = None
    generate_password_hash = None


def hash_password(password: str) -> str:
    password = str(password or "")
    if generate_password_hash is not None:
        return generate_password_hash(password)
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), 260_000)
    return f"pbkdf2_sha256${salt}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    password = str(password or "")
    password_hash = str(password_hash or "")
    if not password_hash:
        return False
    if check_password_hash is not None and not password_hash.startswith("pbkdf2_sha256$"):
        return check_password_hash(password_hash, password)
    try:
        _, salt, digest = password_hash.split("$", 2)
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), 260_000).hex()
        return secrets.compare_digest(candidate, digest)
    except Exception:
        return False


def safe_join(base: str | os.PathLike[str], *parts: str | os.PathLike[str]) -> Path:
    root = Path(base).resolve()
    candidate = root
    for part in parts:
        text = os.fspath(part)
        if not text:
            continue
        child = Path(text)
        if child.is_absolute():
            raise ValueError(f"Absolute paths are not allowed: {text}")
        candidate = candidate / child
    resolved = candidate.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"Unsafe path outside {root}: {candidate}")
    return resolved


def read_json(path: str | os.PathLike[str], default: Any = None) -> Any:
    """Read JSON, transparently decrypting Money Manager encrypted envelopes.

    System/app config files remain plaintext because they are needed before a
    user vault exists. User data paths use secure storage when encrypted.
    """
    target = Path(path)
    try:
        if not target.exists():
            return default
        if _looks_encrypted(target):
            from money_manager.security.secure_storage import read_json_secure

            return read_json_secure(target, default)
        return json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json_atomic(path: str | os.PathLike[str], payload: Any) -> None:
    """Write JSON atomically, using encryption for protected user data paths."""
    target = Path(path)
    if _must_remain_plaintext(target):
        _write_json_plain_atomic(target, payload)
        return
    try:
        from money_manager.security.secure_storage import write_json_secure

        write_json_secure(target, payload)
    except Exception:
        # Compatibility fallback for non-user paths or early bootstrap. Never use
        # this for already-encrypted files: those should fail loudly instead.
        if _looks_encrypted(target):
            raise
        _write_json_plain_atomic(target, payload)


def read_json_plain(path: str | os.PathLike[str], default: Any = None) -> Any:
    try:
        target = Path(path)
        if not target.exists():
            return default
        return json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json_plain_atomic(path: str | os.PathLike[str], payload: Any) -> None:
    _write_json_plain_atomic(Path(path), payload)


def _write_json_plain_atomic(target: Path, payload: Any) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", delete=False, dir=str(target.parent), prefix=f".{target.stem}.", suffix=".tmp", encoding="utf-8") as tmp:
        json.dump(payload, tmp, indent=2, ensure_ascii=False)
        temp_name = tmp.name
    Path(temp_name).replace(target)


def _looks_encrypted(path: Path) -> bool:
    try:
        if not path.exists() or not path.is_file():
            return False
        with path.open("rb") as handle:
            return handle.read(7) == b"MMENC1\n"
    except OSError:
        return False


def _must_remain_plaintext(path: Path) -> bool:
    try:
        from money_manager.config.install_paths import APP_CONFIG_DIR, SYSTEM_DIR

        resolved = path.resolve()
        system = SYSTEM_DIR.resolve()
        app_config = APP_CONFIG_DIR.resolve()
        if resolved == system / "users.json":
            return True
        if system in resolved.parents and "security" in resolved.parts:
            return True
        if resolved == app_config or app_config in resolved.parents:
            return True
    except Exception:
        return False
    return False


class ProtectionManager:
    """Facade for password hashing, path safety, JSON, and secure variants."""

    @staticmethod
    def encryption_enabled(user_id: str | None = None) -> bool:
        try:
            from money_manager.security.key_manager import is_encryption_enabled

            return is_encryption_enabled(user_id)
        except Exception:
            return False

    @staticmethod
    def hash_password(password: str) -> str:
        return hash_password(password)

    @staticmethod
    def verify_password(password: str, password_hash: str) -> bool:
        return verify_password(password, password_hash)

    @staticmethod
    def safe_join(base: str | os.PathLike[str], *parts: str | os.PathLike[str]) -> Path:
        return safe_join(base, *parts)

    @staticmethod
    def read_json(path: str | os.PathLike[str], default: Any = None) -> Any:
        return read_json(path, default)

    @staticmethod
    def write_json_atomic(path: str | os.PathLike[str], payload: Any) -> None:
        write_json_atomic(path, payload)

    @staticmethod
    def read_json_secure(path: str | os.PathLike[str], default: Any = None, user_id: str | None = None) -> Any:
        from money_manager.security.secure_storage import read_json_secure

        return read_json_secure(path, default, user_id=user_id)

    @staticmethod
    def write_json_secure(path: str | os.PathLike[str], payload: Any, user_id: str | None = None) -> None:
        from money_manager.security.secure_storage import write_json_secure

        write_json_secure(path, payload, user_id=user_id)
