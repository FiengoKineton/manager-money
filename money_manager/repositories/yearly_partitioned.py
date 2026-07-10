from __future__ import annotations

import hashlib
import json
import re
import threading
from functools import wraps
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from money_manager.config.user_paths import get_user_data_dir
from money_manager.repositories.csv_files import append_row, read_rows, write_rows
from money_manager.security.secure_storage import (
    read_json_secure,
    secure_delete,
    secure_read_bytes,
    secure_write_bytes,
    write_json_secure,
)

_YEAR_RE = re.compile(r"^(?P<prefix>[a-z0-9_]+)_(?P<year>\d{4})\.csv$", re.IGNORECASE)

_PARTITION_LOCK = threading.RLock()


def _partition_locked(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with _PARTITION_LOCK:
            return function(*args, **kwargs)
    return wrapped


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _money(value: Any) -> float:
    try:
        return float(str(value or "0").replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def _text(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.casefold() in {"nan", "nat", "none", "null"} else text


def _row_year(row: Mapping[str, Any], date_field: str) -> int:
    for field in dict.fromkeys((date_field, "date", "effective_date", "created_at", "updated_at")):
        text = _text(row.get(field))
        if not text:
            continue
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if 1900 <= parsed.year <= 2200:
                return parsed.year
        except ValueError:
            try:
                parsed_date = date.fromisoformat(text[:10])
                if 1900 <= parsed_date.year <= 2200:
                    return parsed_date.year
            except ValueError:
                continue
    return date.today().year




def _as_local_naive_datetime(value: Any, *, end_of_day: bool = False) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime.max.time() if end_of_day else datetime.min.time())
    else:
        text = _text(value)
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed_date = date.fromisoformat(text[:10])
            except ValueError:
                return None
            parsed = datetime.combine(parsed_date, datetime.max.time() if end_of_day else datetime.min.time())
        else:
            # A date-only ISO value parses at midnight. For an inclusive end
            # bound, treat it as the end of that calendar day.
            if end_of_day and "T" not in text and " " not in text:
                parsed = datetime.combine(parsed.date(), datetime.max.time())
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed


def _row_datetime(row: Mapping[str, Any], date_field: str) -> datetime | None:
    for field in dict.fromkeys((date_field, "date", "effective_date", "created_at", "updated_at")):
        parsed = _as_local_naive_datetime(row.get(field))
        if parsed is not None:
            return parsed
    return None


def _canonical_rows_fingerprint(rows: Iterable[Mapping[str, Any]], fields: Iterable[str]) -> str:
    ordered = []
    field_list = list(fields)
    for row in rows:
        ordered.append({field: _text(row.get(field)) for field in field_list})
    raw = json.dumps(ordered, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:24]


@dataclass(frozen=True)
class YearlyDatasetSpec:
    name: str
    legacy_filename: str
    folder_name: str
    file_prefix: str
    fields: tuple[str, ...]
    date_field: str = "date"
    id_field: str = "id"
    signed_value: Callable[[Mapping[str, Any]], float] | None = None
    account_values: Callable[[Mapping[str, Any]], Mapping[str, float]] | None = None
    account_totals_for_rows: Callable[[list[Mapping[str, Any]], str | None], Mapping[str, float]] | None = None
    account_counts_for_rows: Callable[[list[Mapping[str, Any]], str | None], Mapping[str, int]] | None = None
    normalize_row: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None
    context_fingerprint: Callable[[str | None], str] | None = None

    @property
    def summary_filename(self) -> str:
        return f"{self.file_prefix}_summary.json"


class YearlyPartitionError(RuntimeError):
    pass


def _normalized_row(spec: YearlyDatasetSpec, source: Mapping[str, Any]) -> dict[str, Any]:
    candidate = spec.normalize_row(source) if spec.normalize_row else source
    return {field: candidate.get(field, "") for field in spec.fields}


def dataset_root(spec: YearlyDatasetSpec, user_id: str | None = None) -> Path:
    return get_user_data_dir(user_id) / spec.folder_name


def legacy_path(spec: YearlyDatasetSpec, user_id: str | None = None) -> Path:
    return get_user_data_dir(user_id) / spec.legacy_filename


def summary_path(spec: YearlyDatasetSpec, user_id: str | None = None) -> Path:
    return dataset_root(spec, user_id=user_id) / spec.summary_filename


def yearly_path(spec: YearlyDatasetSpec, year: int, user_id: str | None = None) -> Path:
    return dataset_root(spec, user_id=user_id) / f"{spec.file_prefix}_{int(year):04d}.csv"


def archive_path(spec: YearlyDatasetSpec, user_id: str | None = None) -> Path:
    return get_user_data_dir(user_id) / "legacy_archive" / "yearly_partition" / spec.legacy_filename


def discover_years(spec: YearlyDatasetSpec, user_id: str | None = None) -> list[int]:
    root = dataset_root(spec, user_id=user_id)
    if not root.exists():
        return []
    years: list[int] = []
    for path in root.glob(f"{spec.file_prefix}_*.csv"):
        match = _YEAR_RE.match(path.name)
        if match and match.group("prefix").casefold() == spec.file_prefix.casefold():
            years.append(int(match.group("year")))
    return sorted(set(years))


def years_for_range(start: Any = None, end: Any = None) -> list[int] | None:
    if not start and not end:
        return None

    def parse(value: Any, fallback: date) -> date:
        text = _text(value)
        if not text:
            return fallback
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                return date.fromisoformat(text[:10])
            except ValueError:
                return fallback

    start_date = parse(start, date(1900, 1, 1))
    end_date = parse(end, date(2200, 12, 31))
    if end_date < start_date:
        start_date, end_date = end_date, start_date
    return list(range(start_date.year, end_date.year + 1))


def load_summary(spec: YearlyDatasetSpec, user_id: str | None = None) -> dict[str, Any]:
    payload = read_json_secure(summary_path(spec, user_id=user_id), default={}, user_id=user_id)
    return payload if isinstance(payload, dict) else {}


@_partition_locked
def ensure_partitioned(spec: YearlyDatasetSpec, user_id: str | None = None) -> dict[str, Any]:
    """Ensure a valid yearly structure exists without deleting authoritative rows."""
    root = dataset_root(spec, user_id=user_id)
    root.mkdir(parents=True, exist_ok=True)
    years = discover_years(spec, user_id=user_id)
    summary = load_summary(spec, user_id=user_id)
    legacy = legacy_path(spec, user_id=user_id)

    # Until the validated legacy file is archived, it remains authoritative.
    # This also makes an interrupted migration resumable: partial yearly files
    # are safely overwritten from the untouched source on the next startup.
    if legacy.exists() and legacy.is_file() and not (summary.get("migration") or {}).get("completed_at"):
        return migrate_legacy_file(spec, user_id=user_id)
    if years and not _summary_matches_files(spec, summary, user_id=user_id):
        return rebuild_summary(spec, user_id=user_id, repair=True)
    if not years and not summary:
        return rebuild_summary(spec, user_id=user_id, repair=True)
    return summary


@_partition_locked
def read_partitioned_rows(
    spec: YearlyDatasetSpec,
    *,
    user_id: str | None = None,
    years: Iterable[int] | None = None,
    start: Any = None,
    end: Any = None,
) -> list[dict[str, Any]]:
    ensure_partitioned(spec, user_id=user_id)
    selected_years = list(years) if years is not None else years_for_range(start, end)
    if selected_years is None:
        selected_years = discover_years(spec, user_id=user_id)
    rows: list[dict[str, Any]] = []
    for year in sorted(set(int(value) for value in selected_years)):
        path = yearly_path(spec, year, user_id=user_id)
        if path.exists():
            rows.extend(_normalized_row(spec, row) for row in read_rows(path, list(spec.fields)))

    start_dt = _as_local_naive_datetime(start)
    end_dt = _as_local_naive_datetime(end, end_of_day=True)
    if start_dt is None and end_dt is None:
        return rows
    filtered: list[dict[str, Any]] = []
    for row in rows:
        row_dt = _row_datetime(row, spec.date_field)
        if row_dt is None:
            continue
        if start_dt is not None and row_dt < start_dt:
            continue
        if end_dt is not None and row_dt > end_dt:
            continue
        filtered.append(row)
    return filtered


@_partition_locked
def append_partitioned_row(spec: YearlyDatasetSpec, row: Mapping[str, Any], user_id: str | None = None) -> None:
    ensure_partitioned(spec, user_id=user_id)
    year = _row_year(row, spec.date_field)
    path = yearly_path(spec, year, user_id=user_id)
    append_row(path, list(spec.fields), dict(row))
    _refresh_changed_year(spec, year, user_id=user_id)


@_partition_locked
def next_partitioned_id(spec: YearlyDatasetSpec, user_id: str | None = None) -> int:
    summary = ensure_partitioned(spec, user_id=user_id)
    try:
        return int(summary.get("max_numeric_id") or 0) + 1
    except (TypeError, ValueError):
        return 1


@_partition_locked
def replace_partitioned_rows(spec: YearlyDatasetSpec, rows: Iterable[Mapping[str, Any]], user_id: str | None = None) -> dict[str, Any]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    for source in rows:
        row = _normalized_row(spec, source)
        grouped.setdefault(_row_year(row, spec.date_field), []).append(row)

    root = dataset_root(spec, user_id=user_id)
    root.mkdir(parents=True, exist_ok=True)
    existing_years = set(discover_years(spec, user_id=user_id))
    for year, year_rows in grouped.items():
        write_rows(yearly_path(spec, year, user_id=user_id), list(spec.fields), year_rows)
    for year in existing_years - set(grouped):
        secure_delete(user_id, yearly_path(spec, year, user_id=user_id))
    return rebuild_summary(spec, user_id=user_id, repair=False)


@_partition_locked
def mutate_partitioned_row(
    spec: YearlyDatasetSpec,
    predicate: Callable[[Mapping[str, Any]], bool],
    *,
    update: Mapping[str, Any] | None = None,
    delete: bool = False,
    user_id: str | None = None,
) -> bool:
    ensure_partitioned(spec, user_id=user_id)
    for year in discover_years(spec, user_id=user_id):
        path = yearly_path(spec, year, user_id=user_id)
        rows = read_rows(path, list(spec.fields))
        for index, row in enumerate(rows):
            if not predicate(row):
                continue
            old_year = year
            if delete:
                rows.pop(index)
                if rows:
                    write_rows(path, list(spec.fields), rows)
                else:
                    secure_delete(user_id, path)
                _refresh_changed_year(spec, old_year, user_id=user_id)
                return True
            replacement = dict(row)
            for field, value in (update or {}).items():
                if field in spec.fields:
                    replacement[field] = value
            new_year = _row_year(replacement, spec.date_field)
            if new_year == old_year:
                rows[index] = replacement
                write_rows(path, list(spec.fields), rows)
                _refresh_changed_year(spec, old_year, user_id=user_id)
            else:
                rows.pop(index)
                if rows:
                    write_rows(path, list(spec.fields), rows)
                else:
                    secure_delete(user_id, path)
                target_rows = read_rows(yearly_path(spec, new_year, user_id=user_id), list(spec.fields))
                target_rows.append(replacement)
                write_rows(yearly_path(spec, new_year, user_id=user_id), list(spec.fields), target_rows)
                _refresh_changed_year(spec, old_year, user_id=user_id)
                _refresh_changed_year(spec, new_year, user_id=user_id)
            return True
    return False


@_partition_locked
def migrate_legacy_file(spec: YearlyDatasetSpec, user_id: str | None = None) -> dict[str, Any]:
    legacy = legacy_path(spec, user_id=user_id)
    if not legacy.exists():
        return rebuild_summary(spec, user_id=user_id, repair=True)
    rows = read_rows(legacy, list(spec.fields))
    grouped: dict[int, list[dict[str, Any]]] = {}
    for source in rows:
        row = _normalized_row(spec, source)
        grouped.setdefault(_row_year(row, spec.date_field), []).append(row)
    existing_years = set(discover_years(spec, user_id=user_id))
    for year, year_rows in grouped.items():
        write_rows(yearly_path(spec, year, user_id=user_id), list(spec.fields), year_rows)
    for year in existing_years - set(grouped):
        secure_delete(user_id, yearly_path(spec, year, user_id=user_id))

    rebuilt = rebuild_summary(spec, user_id=user_id, repair=False)
    if int(rebuilt.get("row_count") or 0) != len(rows):
        raise YearlyPartitionError(
            f"{spec.name}: migration validation failed ({len(rows)} source rows, {rebuilt.get('row_count')} partition rows)."
        )

    destination = archive_path(spec, user_id=user_id)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        destination = destination.with_name(f"{destination.stem}_{timestamp}{destination.suffix}")
    # Preserve the exact logical legacy source as an encrypted archive even
    # when the imported/old source happened to be plaintext.
    legacy_payload = secure_read_bytes(user_id, legacy)
    secure_write_bytes(user_id, destination, legacy_payload)
    secure_delete(user_id, legacy)
    rebuilt["migration"] = {
        "completed_at": _utc_now(),
        "source": spec.legacy_filename,
        "archived_to": destination.relative_to(get_user_data_dir(user_id)).as_posix(),
        "source_rows": len(rows),
    }
    write_json_secure(summary_path(spec, user_id=user_id), rebuilt, user_id=user_id)
    return rebuilt


@_partition_locked
def rebuild_summary(spec: YearlyDatasetSpec, user_id: str | None = None, *, repair: bool = True) -> dict[str, Any]:
    """Rebuild and optionally repair misplaced yearly rows without deleting data."""
    previous_summary = load_summary(spec, user_id=user_id)
    root = dataset_root(spec, user_id=user_id)
    root.mkdir(parents=True, exist_ok=True)
    rows_by_year: dict[int, list[dict[str, Any]]] = {}
    duplicate_ids: list[str] = []
    seen_ids: set[str] = set()
    moved_rows = 0

    for stored_year in discover_years(spec, user_id=user_id):
        path = yearly_path(spec, stored_year, user_id=user_id)
        for source in read_rows(path, list(spec.fields)):
            row = _normalized_row(spec, source)
            actual_year = _row_year(row, spec.date_field)
            if actual_year != stored_year:
                moved_rows += 1
            row_id = _text(row.get(spec.id_field))
            if row_id and row_id in seen_ids:
                # Never delete data during an integrity refresh. Duplicate IDs
                # are reported so the user can inspect them, while every row is
                # retained in its correct yearly file.
                duplicate_ids.append(row_id)
            if row_id:
                seen_ids.add(row_id)
            rows_by_year.setdefault(actual_year if repair else stored_year, []).append(row)

    if repair and moved_rows:
        existing = set(discover_years(spec, user_id=user_id))
        for year, rows in rows_by_year.items():
            write_rows(yearly_path(spec, year, user_id=user_id), list(spec.fields), rows)
        for year in existing - set(rows_by_year):
            secure_delete(user_id, yearly_path(spec, year, user_id=user_id))

    summary = _build_summary(spec, rows_by_year, user_id=user_id)
    if isinstance(previous_summary.get("migration"), Mapping):
        summary["migration"] = dict(previous_summary["migration"])
    summary["validation"] = {
        "repaired": bool(repair and moved_rows),
        "moved_rows": moved_rows,
        "duplicate_ids_found": sorted(set(duplicate_ids)),
        "duplicate_ids_removed": [],
    }
    write_json_secure(summary_path(spec, user_id=user_id), summary, user_id=user_id)
    return summary


def _year_entry(spec: YearlyDatasetSpec, year: int, rows: list[dict[str, Any]], user_id: str | None = None) -> dict[str, Any]:
    signed_total = sum(spec.signed_value(row) if spec.signed_value else _money(row.get("amount")) for row in rows)
    gross_total = sum(abs(_money(row.get("amount"))) for row in rows)
    date_values = sorted(value for value in (_text(row.get(spec.date_field)) for row in rows) if value)
    account_totals: dict[str, float] = {}
    if spec.account_totals_for_rows:
        account_totals = {
            str(key): float(value)
            for key, value in spec.account_totals_for_rows(rows, user_id).items()
            if str(key or "").strip()
        }
    elif spec.account_values:
        for row in rows:
            for key, value in spec.account_values(row).items():
                if key:
                    account_totals[key] = account_totals.get(key, 0.0) + float(value)
    account_counts: dict[str, int] = {}
    if spec.account_counts_for_rows:
        account_counts = {
            str(key): int(value)
            for key, value in spec.account_counts_for_rows(rows, user_id).items()
            if str(key or "").strip()
        }
    numeric_ids = [int(_text(row.get(spec.id_field))) for row in rows if _text(row.get(spec.id_field)).isdigit()]
    path = yearly_path(spec, year, user_id=user_id)
    try:
        stat = path.stat()
        physical_size = int(stat.st_size)
        physical_mtime_ns = int(stat.st_mtime_ns)
    except OSError:
        physical_size = 0
        physical_mtime_ns = 0
    return {
        "file": path.name,
        "row_count": len(rows),
        "first_timestamp": date_values[0] if date_values else "",
        "last_timestamp": date_values[-1] if date_values else "",
        "gross_total": round(gross_total, 2),
        "signed_total": round(signed_total, 2),
        "opening_cumulative": 0.0,
        "closing_cumulative": 0.0,
        "max_numeric_id": max(numeric_ids, default=0),
        "totals_by_account": {key: round(value, 2) for key, value in sorted(account_totals.items())},
        "row_counts_by_account": {key: int(value) for key, value in sorted(account_counts.items())},
        "content_fingerprint": _canonical_rows_fingerprint(rows, spec.fields),
        "physical_size": physical_size,
        "physical_mtime_ns": physical_mtime_ns,
    }


def _summary_from_entries(spec: YearlyDatasetSpec, entries: Mapping[int, Mapping[str, Any]], user_id: str | None = None) -> dict[str, Any]:
    years_payload: dict[str, Any] = {}
    cumulative = 0.0
    gross_cumulative = 0.0
    max_numeric_id = 0
    total_rows = 0
    global_account_totals: dict[str, float] = {}
    global_account_counts: dict[str, int] = {}
    for year in sorted(entries):
        entry = dict(entries[year])
        opening = cumulative
        gross_opening = gross_cumulative
        cumulative += _money(entry.get("signed_total"))
        gross_cumulative += _money(entry.get("gross_total"))
        entry["opening_cumulative"] = round(opening, 2)
        entry["closing_cumulative"] = round(cumulative, 2)
        entry["opening_gross_cumulative"] = round(gross_opening, 2)
        entry["closing_gross_cumulative"] = round(gross_cumulative, 2)
        total_rows += int(entry.get("row_count") or 0)
        max_numeric_id = max(max_numeric_id, int(entry.get("max_numeric_id") or 0))
        for key, value in (entry.get("totals_by_account") or {}).items():
            global_account_totals[str(key)] = global_account_totals.get(str(key), 0.0) + _money(value)
        for key, value in (entry.get("row_counts_by_account") or {}).items():
            global_account_counts[str(key)] = global_account_counts.get(str(key), 0) + int(value or 0)
        years_payload[str(year)] = entry
    return {
        "schema_version": 1,
        "dataset": spec.name,
        "authoritative_source": "encrypted_yearly_csv",
        "generated_at": _utc_now(),
        "available_years": sorted(entries),
        "row_count": total_rows,
        "max_numeric_id": max_numeric_id,
        "signed_total": round(cumulative, 2),
        "gross_total": round(gross_cumulative, 2),
        "totals_by_account": {key: round(value, 2) for key, value in sorted(global_account_totals.items())},
        "row_counts_by_account": {key: int(value) for key, value in sorted(global_account_counts.items())},
        "years": years_payload,
        "context_fingerprint": spec.context_fingerprint(user_id) if spec.context_fingerprint else "",
    }


def _build_summary(spec: YearlyDatasetSpec, rows_by_year: Mapping[int, list[dict[str, Any]]], user_id: str | None = None) -> dict[str, Any]:
    entries = {year: _year_entry(spec, year, rows, user_id=user_id) for year, rows in rows_by_year.items()}
    return _summary_from_entries(spec, entries, user_id=user_id)

def _summary_matches_files(spec: YearlyDatasetSpec, summary: Mapping[str, Any], user_id: str | None = None) -> bool:
    years = discover_years(spec, user_id=user_id)
    if spec.context_fingerprint and str(summary.get("context_fingerprint") or "") != spec.context_fingerprint(user_id):
        return False
    if sorted(summary.get("available_years") or []) != years:
        return False
    payload = summary.get("years") if isinstance(summary.get("years"), Mapping) else {}
    for year in years:
        entry = payload.get(str(year)) if isinstance(payload, Mapping) else None
        if not isinstance(entry, Mapping):
            return False
        path = yearly_path(spec, year, user_id=user_id)
        try:
            stat = path.stat()
        except OSError:
            return False
        if int(entry.get("physical_size") or -1) != int(stat.st_size):
            return False
        if int(entry.get("physical_mtime_ns") or -1) != int(stat.st_mtime_ns):
            return False
    return bool(summary.get("schema_version") == 1 and summary.get("dataset") == spec.name)


def _refresh_changed_year(spec: YearlyDatasetSpec, year: int, user_id: str | None = None) -> dict[str, Any]:
    """Refresh one yearly entry and derive all cumulative values from the index.

    Normal writes decrypt only the affected year's CSV. Older years are reused
    from the validated summary, so adding a 2027 row does not reread 2025/2026.
    A full rebuild remains available from Integrity for deliberate verification.
    """
    previous = load_summary(spec, user_id=user_id)
    if spec.context_fingerprint and str(previous.get("context_fingerprint") or "") != spec.context_fingerprint(user_id):
        return rebuild_summary(spec, user_id=user_id, repair=False)
    previous_years = previous.get("years") if isinstance(previous.get("years"), Mapping) else {}
    entries: dict[int, Mapping[str, Any]] = {}
    for candidate in discover_years(spec, user_id=user_id):
        if candidate == year:
            rows = [_normalized_row(spec, row) for row in read_rows(yearly_path(spec, candidate, user_id=user_id), list(spec.fields))]
            entries[candidate] = _year_entry(spec, candidate, rows, user_id=user_id)
            continue
        cached = previous_years.get(str(candidate)) if isinstance(previous_years, Mapping) else None
        path = yearly_path(spec, candidate, user_id=user_id)
        try:
            stat = path.stat()
            cache_valid = bool(
                isinstance(cached, Mapping)
                and int(cached.get("physical_size") or -1) == int(stat.st_size)
                and int(cached.get("physical_mtime_ns") or -1) == int(stat.st_mtime_ns)
            )
        except OSError:
            cache_valid = False
        if cache_valid:
            entries[candidate] = dict(cached)
        else:
            rows = [_normalized_row(spec, row) for row in read_rows(path, list(spec.fields))]
            entries[candidate] = _year_entry(spec, candidate, rows, user_id=user_id)
    rebuilt = _summary_from_entries(spec, entries, user_id=user_id)
    if isinstance(previous.get("migration"), Mapping):
        rebuilt["migration"] = dict(previous["migration"])
    write_json_secure(summary_path(spec, user_id=user_id), rebuilt, user_id=user_id)
    return rebuilt

