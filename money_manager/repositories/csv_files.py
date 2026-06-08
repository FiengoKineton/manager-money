import csv
from pathlib import Path
from typing import Iterable


def ensure_csv(path: Path, fieldnames: list[str]) -> None:
    """Create or migrate a CSV file so it has the requested headers.

    Existing rows are preserved when new columns are added. This lets the app
    evolve its data model without manually editing old CSV files.
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

    missing_headers = [field for field in fieldnames if field not in existing_headers]
    if not missing_headers:
        return

    merged_headers = [*existing_headers, *missing_headers]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=merged_headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in merged_headers})


def read_rows(path: Path, fieldnames: list[str]) -> list[dict]:
    ensure_csv(path, fieldnames)
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_rows(path: Path, fieldnames: list[str], rows: Iterable[dict]) -> None:
    ensure_csv(path, fieldnames)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def append_row(path: Path, fieldnames: list[str], row: dict) -> None:
    ensure_csv(path, fieldnames)
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writerow({field: row.get(field, "") for field in fieldnames})


def next_numeric_id(rows: list[dict], field: str = "id") -> int:
    ids = [int(row[field]) for row in rows if str(row.get(field, "")).isdigit()]
    return max(ids, default=0) + 1
