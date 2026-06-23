from __future__ import annotations

import hashlib
import json
import re
from typing import Any

SENSITIVE_PARAM_NAMES = {"password", "secret", "token", "dek", "key", "iban", "bic", "swift"}


def canonical_json(value: Any) -> str:
    """Return a deterministic, compact JSON representation for keying."""
    try:
        return json.dumps(_normalize(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    except TypeError:
        return json.dumps(str(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest_text(value: str, length: int = 32) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:length]


def digest_payload(value: Any, length: int = 32) -> str:
    return digest_text(canonical_json(value), length=length)


def safe_name(value: str, *, max_length: int = 80) -> str:
    text = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(value or "")).strip("_.-")
    if not text:
        text = "cache"
    if len(text) > max_length:
        text = f"{text[:max_length-13]}_{digest_text(text, 12)}"
    return text


def sanitize_params(params: dict[str, Any] | None) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in sorted(dict(params or {}).items()):
        key_text = str(key)
        if any(part in key_text.casefold() for part in SENSITIVE_PARAM_NAMES):
            result[key_text] = {"sha256": digest_payload(value)}
        elif isinstance(value, (str, int, float, bool)) or value is None:
            text = str(value) if isinstance(value, str) else value
            if isinstance(text, str) and len(text) > 80:
                result[key_text] = {"sha256": digest_text(text)}
            else:
                result[key_text] = text
        else:
            result[key_text] = {"sha256": digest_payload(value)}
    return result


def build_cache_key(*, user_id: str, name: str, version: str, params: dict[str, Any] | None, source_fingerprint: dict[str, Any] | str | None) -> str:
    if isinstance(source_fingerprint, str):
        source_hash = source_fingerprint
    else:
        source_hash = digest_payload(source_fingerprint or {})
    payload = {
        "user_id": str(user_id or ""),
        "name": str(name or ""),
        "version": str(version or ""),
        "params": sanitize_params(params),
        "source_fingerprint": source_hash,
    }
    return f"user:{payload['user_id']}:{payload['name']}:{payload['version']}:{digest_payload(payload, 24)}"


def hashed_entry_id(key: str) -> str:
    return digest_text(key, length=40)


def _normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _normalize(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple, set)):
        return [_normalize(item) for item in value]
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    return value
