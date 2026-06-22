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
    try:
        target = Path(path)
        if not target.exists():
            return default
        return json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json_atomic(path: str | os.PathLike[str], payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", delete=False, dir=str(target.parent), prefix=f".{target.stem}.", suffix=".tmp", encoding="utf-8") as tmp:
        json.dump(payload, tmp, indent=2, ensure_ascii=False)
        temp_name = tmp.name
    Path(temp_name).replace(target)


class ProtectionManager:
    """Placeholder facade for future encryption-at-rest support."""

    encryption_enabled = False

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
