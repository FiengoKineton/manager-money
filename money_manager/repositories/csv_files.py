import csv
from pathlib import Path
from typing import Iterable


def ensure_csv(path: Path, fieldnames: list[str]) -> None:
    """Create or migrate a CSV file so it has the requested headers.

    Existing rows are preserved when new columns are added.  The requested
    fieldnames are kept first and in the correct order so later appends do not
    accidentally write values under the wrong columns after a schema migration.
    Any unknown extra columns are kept after the requested schema.
    """
    path.parent.mkdir(exist_ok=True, parents=True)

    if not path.exists() or path.stat().st_size == 0:
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
        return

    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        existing_headers = reader.fieldnames or []
        rows = list(reader)

    desired_headers = [*fieldnames, *[header for header in existing_headers if header not in fieldnames]]
    if existing_headers == desired_headers:
        return

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=desired_headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in desired_headers})


def _current_headers(path: Path, fallback: list[str]) -> list[str]:
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            headers = next(reader, [])
            return headers or fallback
    except OSError:
        return fallback


def read_rows(path: Path, fieldnames: list[str]) -> list[dict]:
    ensure_csv(path, fieldnames)
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_rows(path: Path, fieldnames: list[str], rows: Iterable[dict]) -> None:
    ensure_csv(path, fieldnames)
    headers = _current_headers(path, fieldnames)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in headers})


def append_row(path: Path, fieldnames: list[str], row: dict) -> None:
    ensure_csv(path, fieldnames)
    headers = _current_headers(path, fieldnames)
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writerow({field: row.get(field, "") for field in headers})


def next_numeric_id(rows: list[dict], field: str = "id") -> int:
    ids = [int(row[field]) for row in rows if str(row.get(field, "")).isdigit()]
    return max(ids, default=0) + 1
