from pathlib import Path

from money_manager.config import (
    ALLOWED_DOCUMENT_EXTENSIONS,
    DOCUMENT_FOLDERS,
)
from money_manager.config.user_paths import user_documents_dir
from money_manager.security.protection_manager import safe_join


def is_allowed_folder(folder: str) -> bool:
    return folder in DOCUMENT_FOLDERS


def is_allowed_document(filename: str) -> bool:
    """Return True only for file types the document viewer is allowed to expose."""
    return Path(filename).suffix.lower() in ALLOWED_DOCUMENT_EXTENSIONS


def folder_path(folder: str) -> Path:
    if not is_allowed_folder(folder):
        raise ValueError(f"Invalid document folder: {folder}")

    return safe_join(user_documents_dir(), folder)


def document_path(folder: str, filename: str) -> Path:
    if not is_allowed_document(filename):
        raise ValueError(f"Invalid document file: {filename}")
    return safe_join(folder_path(folder), filename)


def list_files(folder: str) -> list[str]:
    path = folder_path(folder)

    if not path.exists():
        return []

    return sorted(
        item.name
        for item in path.iterdir()
        if item.is_file() and is_allowed_document(item.name)
    )
