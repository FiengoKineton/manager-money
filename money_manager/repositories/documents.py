from pathlib import Path

from money_manager.config import (
    ALLOWED_DOCUMENT_EXTENSIONS,
    DOCUMENTS_DIR,
    DOCUMENT_FOLDERS,
)


def is_allowed_folder(folder: str) -> bool:
    return folder in DOCUMENT_FOLDERS


def is_allowed_document(filename: str) -> bool:
    """Return True only for file types the document viewer is allowed to expose."""
    return Path(filename).suffix.lower() in ALLOWED_DOCUMENT_EXTENSIONS


def folder_path(folder: str) -> Path:
    if not is_allowed_folder(folder):
        raise ValueError(f"Invalid document folder: {folder}")

    return DOCUMENTS_DIR / folder


def list_files(folder: str) -> list[str]:
    path = folder_path(folder)

    if not path.exists():
        return []

    return sorted(
        item.name
        for item in path.iterdir()
        if item.is_file() and is_allowed_document(item.name)
    )