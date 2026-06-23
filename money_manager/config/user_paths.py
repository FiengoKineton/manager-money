from __future__ import annotations

import contextlib
import contextvars
import os
import re
from pathlib import Path
from typing import Callable, Iterator

try:
    from flask import has_request_context, session
except Exception:  # allows launcher/update tools to run before Flask is installed
    def has_request_context() -> bool:
        return False

    session = {}

from money_manager.config.install_paths import DATA_DIR, PROJECT_ROOT, SYSTEM_DIR, USERS_DIR

_current_user_override: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "money_manager_current_user_id", default=None
)


def normalize_user_id(value: str | None) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9_-]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_-")
    return text[:64] or "user"


def get_current_user_id() -> str | None:
    override = _current_user_override.get()
    if override:
        return normalize_user_id(override)
    if has_request_context():
        user_id = session.get("user_id")
        if user_id:
            return normalize_user_id(str(user_id))
    return None


@contextlib.contextmanager
def using_user(user_id: str | None) -> Iterator[None]:
    token = _current_user_override.set(normalize_user_id(user_id) if user_id else None)
    try:
        yield
    finally:
        _current_user_override.reset(token)


def _require_user_id(user_id: str | None = None) -> str:
    resolved = user_id or get_current_user_id()
    if not resolved:
        raise RuntimeError("No authenticated Money Manager user is available for this data path.")
    return normalize_user_id(resolved)


def _safe_child(base: Path, *parts: str | os.PathLike[str]) -> Path:
    root = base.resolve()
    candidate = root
    for part in parts:
        text = os.fspath(part)
        if not text:
            continue
        piece = Path(text)
        if piece.is_absolute():
            raise ValueError(f"Absolute paths are not allowed here: {text}")
        candidate = candidate / piece
    resolved = candidate.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"Unsafe path outside {root}: {candidate}")
    return resolved


def get_user_data_dir(user_id: str | None = None) -> Path:
    return _safe_child(USERS_DIR, _require_user_id(user_id))


def user_data_path(filename: str | os.PathLike[str], user_id: str | None = None):
    if user_id is not None:
        return _safe_child(get_user_data_dir(user_id), filename)
    return RuntimeUserPath(lambda: _safe_child(get_user_data_dir(), filename), f"user_data:{filename}")


def user_cache_dir(user_id: str | None = None):
    if user_id is not None:
        return _safe_child(get_user_data_dir(user_id), "cache")
    return RuntimeUserPath(lambda: _safe_child(get_user_data_dir(), "cache"), "user_cache")


def user_plots_dir(user_id: str | None = None):
    if user_id is not None:
        return _safe_child(get_user_data_dir(user_id), "plots")
    return RuntimeUserPath(lambda: _safe_child(get_user_data_dir(), "plots"), "user_plots")


def user_documents_dir(user_id: str | None = None):
    if user_id is not None:
        return _safe_child(get_user_data_dir(user_id), "documents")
    return RuntimeUserPath(lambda: _safe_child(get_user_data_dir(), "documents"), "user_documents")


def user_plot_path(filename: str | os.PathLike[str], user_id: str | None = None) -> Path:
    return _safe_child(Path(user_plots_dir(user_id)), filename)


def user_document_path(filename: str | os.PathLike[str], user_id: str | None = None) -> Path:
    return _safe_child(Path(user_documents_dir(user_id)), filename)


def transaction_file_path(transaction_type: str, user_id: str | None = None):
    filenames = {
        "expense": "expenses.csv",
        "income": "incomes.csv",
        "investment": "investments.csv",
    }
    try:
        filename = filenames[transaction_type]
    except KeyError as exc:
        raise ValueError(f"Unknown transaction type: {transaction_type}") from exc
    return user_data_path(filename, user_id=user_id)


class RuntimeUserPath(os.PathLike[str]):
    """Path-like object that resolves to the authenticated user's folder at runtime."""

    def __init__(self, resolver: Callable[[], Path], label: str) -> None:
        self._resolver = resolver
        self._label = label

    def resolve_path(self) -> Path:
        return self._resolver()

    def __fspath__(self) -> str:
        return str(self.resolve_path())

    def __str__(self) -> str:
        return str(self.resolve_path())

    def __repr__(self) -> str:
        try:
            return f"RuntimeUserPath({self.resolve_path()!s})"
        except Exception:
            return f"RuntimeUserPath({self._label})"

    def __truediv__(self, other: str | os.PathLike[str]) -> Path:
        return self.resolve_path() / other

    def __getattr__(self, name: str):
        return getattr(self.resolve_path(), name)

    @property
    def parent(self) -> Path:
        return self.resolve_path().parent

    @property
    def name(self) -> str:
        return self.resolve_path().name

    @property
    def suffix(self) -> str:
        return self.resolve_path().suffix

    def exists(self) -> bool:
        return self.resolve_path().exists()

    def is_file(self) -> bool:
        return self.resolve_path().is_file()

    def is_dir(self) -> bool:
        return self.resolve_path().is_dir()

    def mkdir(self, *args, **kwargs):
        return self.resolve_path().mkdir(*args, **kwargs)

    def open(self, *args, **kwargs):
        return self.resolve_path().open(*args, **kwargs)

    def read_text(self, *args, **kwargs):
        return self.resolve_path().read_text(*args, **kwargs)

    def write_text(self, *args, **kwargs):
        return self.resolve_path().write_text(*args, **kwargs)

    def stat(self, *args, **kwargs):
        return self.resolve_path().stat(*args, **kwargs)

    def glob(self, *args, **kwargs):
        return self.resolve_path().glob(*args, **kwargs)
