from __future__ import annotations

from typing import Any

from money_manager.repositories.account_ledger import ACCOUNT_LEDGER_SPEC
from money_manager.repositories.internal_transfers import INTERNAL_TRANSFERS_SPEC
from money_manager.repositories.transactions import partition_spec_for_type
from money_manager.repositories.yearly_partitioned import (
    YearlyDatasetSpec,
    discover_years,
    ensure_partitioned,
    legacy_path,
    load_summary,
    rebuild_summary,
)


def movement_history_specs() -> list[YearlyDatasetSpec]:
    return [
        partition_spec_for_type("expense"),
        partition_spec_for_type("income"),
        partition_spec_for_type("investment"),
        INTERNAL_TRANSFERS_SPEC,
        ACCOUNT_LEDGER_SPEC,
    ]


def movement_history_status(user_id: str | None = None) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for spec in movement_history_specs():
        summary = load_summary(spec, user_id=user_id)
        years = discover_years(spec, user_id=user_id)
        legacy_exists = legacy_path(spec, user_id=user_id).exists()
        rows.append({
            "dataset": spec.name,
            "folder": spec.folder_name,
            "years": years,
            "year_count": len(years),
            "row_count": int(summary.get("row_count") or 0),
            "signed_total": float(summary.get("signed_total") or 0.0),
            "summary_ready": bool(summary and summary.get("schema_version") == 1),
            "legacy_file_exists": legacy_exists,
            "migration": summary.get("migration") if isinstance(summary.get("migration"), dict) else {},
            "validation": summary.get("validation") if isinstance(summary.get("validation"), dict) else {},
        })
    return {
        "ok": all(row["summary_ready"] or row["legacy_file_exists"] for row in rows),
        "datasets": rows,
    }


def refresh_movement_histories(*, confirm: bool, user_id: str | None = None) -> dict[str, Any]:
    if not confirm:
        return {
            "ok": False,
            "error": "Confirm the full movement-history validation before running it.",
            "datasets": [],
        }

    report_rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for spec in movement_history_specs():
        try:
            before_legacy = legacy_path(spec, user_id=user_id).exists()
            ensured = ensure_partitioned(spec, user_id=user_id)
            rebuilt = rebuild_summary(spec, user_id=user_id, repair=True)
            migration = ensured.get("migration") if isinstance(ensured.get("migration"), dict) else {}
            validation = rebuilt.get("validation") if isinstance(rebuilt.get("validation"), dict) else {}
            report_rows.append({
                "dataset": spec.name,
                "folder": spec.folder_name,
                "years": list(rebuilt.get("available_years") or []),
                "row_count": int(rebuilt.get("row_count") or 0),
                "signed_total": float(rebuilt.get("signed_total") or 0.0),
                "migrated": bool(before_legacy and migration),
                "migration": migration,
                "moved_rows": int(validation.get("moved_rows") or 0),
                "duplicate_ids_found": list(validation.get("duplicate_ids_found") or []),
                "summary_ready": True,
            })
        except Exception as exc:
            errors.append(f"{spec.name}: {exc}")
            report_rows.append({
                "dataset": spec.name,
                "folder": spec.folder_name,
                "years": [],
                "row_count": 0,
                "signed_total": 0.0,
                "migrated": False,
                "moved_rows": 0,
                "duplicate_ids_found": [],
                "summary_ready": False,
                "error": str(exc),
            })

    try:
        from money_manager.services.cache_service import notify_data_changed
        notify_data_changed(tags=["money_rows", "account_ledger", "internal_transfers"])
    except Exception:
        pass

    return {
        "ok": not errors,
        "errors": errors,
        "datasets": report_rows,
    }
