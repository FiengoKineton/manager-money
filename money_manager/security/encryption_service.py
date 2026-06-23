from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC_TEXT = "MMENC1"
MAGIC_BYTES = b"MMENC1\n"
ALGORITHM = "AESGCM"
NONCE_BYTES = 12
KEY_BYTES = 32


class EncryptionError(RuntimeError):
    """Base error for encrypted file handling."""


class DecryptionError(EncryptionError):
    """Raised when encrypted bytes cannot be decrypted with the supplied key."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def is_encrypted_bytes(payload: bytes | bytearray | memoryview | None) -> bool:
    return bytes(payload or b"").startswith(MAGIC_BYTES)


def is_file_encrypted(path: str | os.PathLike[str]) -> bool:
    target = Path(path)
    try:
        if not target.exists() or not target.is_file():
            return False
        with target.open("rb") as handle:
            return handle.read(len(MAGIC_BYTES)) == MAGIC_BYTES
    except OSError:
        return False


def encrypt_bytes(
    plaintext: bytes | bytearray | memoryview,
    key: bytes | bytearray | memoryview,
    *,
    content_type: str = "application/octet-stream",
    original_logical_name: str = "",
    original_filename: str = "",
) -> bytes:
    key_bytes = _validate_key(key)
    nonce = os.urandom(NONCE_BYTES)
    aad = _aad(content_type, original_logical_name, original_filename)
    ciphertext = AESGCM(key_bytes).encrypt(nonce, bytes(plaintext), aad)
    envelope = {
        "magic": MAGIC_TEXT,
        "schema_version": 1,
        "algorithm": ALGORITHM,
        "nonce": _b64(nonce),
        "content_type": str(content_type or "application/octet-stream"),
        "original_logical_name": str(original_logical_name or ""),
        "original_filename": str(original_filename or ""),
        "created_at": utc_now(),
        "ciphertext": _b64(ciphertext),
    }
    return MAGIC_BYTES + json.dumps(envelope, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def decrypt_bytes(payload: bytes | bytearray | memoryview, key: bytes | bytearray | memoryview) -> bytes:
    raw = bytes(payload or b"")
    if not is_encrypted_bytes(raw):
        raise DecryptionError("Payload is not a Money Manager encrypted envelope.")
    key_bytes = _validate_key(key)
    try:
        envelope = json.loads(raw[len(MAGIC_BYTES):].decode("utf-8"))
        if envelope.get("magic") != MAGIC_TEXT or envelope.get("algorithm") != ALGORITHM:
            raise DecryptionError("Unsupported encrypted envelope.")
        nonce = _unb64(str(envelope.get("nonce") or ""))
        ciphertext = _unb64(str(envelope.get("ciphertext") or ""))
        aad = _aad(
            str(envelope.get("content_type") or "application/octet-stream"),
            str(envelope.get("original_logical_name") or ""),
            str(envelope.get("original_filename") or ""),
        )
        return AESGCM(key_bytes).decrypt(nonce, ciphertext, aad)
    except InvalidTag as exc:
        raise DecryptionError("Wrong password or corrupted encrypted file.") from exc
    except DecryptionError:
        raise
    except Exception as exc:
        raise DecryptionError("Encrypted file envelope is invalid.") from exc


def encrypt_file_in_place(
    path: str | os.PathLike[str],
    key: bytes | bytearray | memoryview,
    *,
    content_type: str = "application/octet-stream",
    original_logical_name: str = "",
    original_filename: str = "",
) -> bool:
    target = Path(path)
    if not target.exists() or not target.is_file():
        return False
    raw = target.read_bytes()
    if is_encrypted_bytes(raw):
        return False
    encrypted = encrypt_bytes(
        raw,
        key,
        content_type=content_type,
        original_logical_name=original_logical_name or target.name,
        original_filename=original_filename or target.name,
    )
    _atomic_write_bytes(target, encrypted)
    return True


def decrypt_file_to_memory(path: str | os.PathLike[str], key: bytes | bytearray | memoryview) -> bytes:
    target = Path(path)
    raw = target.read_bytes()
    if not is_encrypted_bytes(raw):
        return raw
    return decrypt_bytes(raw, key)


def read_envelope_metadata(path: str | os.PathLike[str]) -> dict[str, Any]:
    target = Path(path)
    if not is_file_encrypted(target):
        return {}
    try:
        raw = target.read_bytes()
        payload = json.loads(raw[len(MAGIC_BYTES):].decode("utf-8"))
        payload.pop("ciphertext", None)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {"magic": MAGIC_TEXT, "invalid": True}


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("wb", delete=False, dir=str(path.parent), prefix=f".{path.stem}.", suffix=".tmp") as tmp:
        tmp.write(payload)
        temp_name = tmp.name
    Path(temp_name).replace(path)


def _validate_key(key: bytes | bytearray | memoryview) -> bytes:
    key_bytes = bytes(key or b"")
    if len(key_bytes) != KEY_BYTES:
        raise EncryptionError("AES-GCM data key must be 256 bits.")
    return key_bytes


def _aad(content_type: str, original_logical_name: str, original_filename: str) -> bytes:
    return json.dumps(
        {
            "magic": MAGIC_TEXT,
            "algorithm": ALGORITHM,
            "content_type": str(content_type or "application/octet-stream"),
            "original_logical_name": str(original_logical_name or ""),
            "original_filename": str(original_filename or ""),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _b64(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).decode("ascii")


def _unb64(payload: str) -> bytes:
    return base64.urlsafe_b64decode(payload.encode("ascii"))
