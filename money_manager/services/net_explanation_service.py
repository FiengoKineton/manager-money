"""Read-only explanations for the money-position numbers.

The goal is transparency, not new accounting.  This module reuses the existing
``overview_service`` and transaction/account services so the values shown here
stay identical to the rest of the app.
"""

from __future__ import annotations

import hashlib
import csv
import json
import os
import subprocess
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Any

import pandas as pd

from money_manager.services.overview_service import build_overview_context
from money_manager.services.transaction_service import load_transactions, prepare_transactions_for_display
from money_manager.utils.stats import summary_totals


MAX_EXPLANATION_ROWS = 80


def build_net_explanation_context(scope: str = "global") -> dict[str, Any]:
    """Build a read-only explanation for the current scoped overview balances."""
    from money_manager.services.account_scope_service import (
        balance_source_breakdown_for_scope,
        transactions_for_scope,
    )

    overview = build_overview_context(scope=scope)
    all_transactions = load_transactions()
    main_transactions = transactions_for_scope(all_transactions, scope)
    main_totals = summary_totals(main_transactions)

    return {
        "overview": overview,
        "headline": _headline_rows(overview),
        "formulas": _formula_rows(overview),
        "main_totals": main_totals,
        "counted_rows": _display_rows(main_transactions, limit=MAX_EXPLANATION_ROWS),
        "excluded_rows": _display_rows(_excluded_liquid_account_rows(all_transactions), limit=MAX_EXPLANATION_ROWS),
        "counted_count": int(len(main_transactions)),
        "excluded_count": int(len(_excluded_liquid_account_rows(all_transactions))),
        "balance_sources": balance_source_breakdown_for_scope(scope, df=all_transactions),
        "data_diagnostics": _data_source_diagnostics(),
        "notes": _notes(),
    }


def _headline_rows(overview: dict[str, Any]) -> list[dict[str, Any]]:
    totals = overview["totals"]
    return [
        {
            "label": "Selected scope net",
            "value": totals["net"],
            "caption": "Same scoped value used in the selected overview/dashboard.",
        },
        {
            "label": "Visible liquidity",
            "value": overview["combined_visible_liquidity"],
            "caption": "Main bank net + separate liquid-account balances.",
        },
        {
            "label": "Main available position",
            "value": overview["cash_position"],
            "caption": "Visible liquidity + invested capital, excluding market profit/loss.",
        },
        {
            "label": "Adjusted stress position",
            "value": overview["adjusted_stress_position"],
            "caption": "Stress position + recoverable receivables + investment profit/loss.",
        },
    ]


def _formula_rows(overview: dict[str, Any]) -> list[dict[str, Any]]:
    totals = overview["totals"]
    aux = overview["auxiliary_balance"]
    visible = overview["combined_visible_liquidity"]
    invested = overview["investment_capital"]
    credit_pending = overview["credit_pending_amount"]
    active_debt = overview["active_debt"]
    receivable = overview["receivable_active_remaining"]
    pnl = overview["investment_profit_loss"]

    return [
        {
            "name": "Selected scope net",
            "formula": "scoped income - scoped expenses - scoped investments ± scoped transfers",
            "parts": [
                _part("Income", totals["income"]),
                _part("Expenses", -totals["expenses"]),
                _part("Investments", -totals["investments"]),
            ],
            "result": totals["net"],
        },
        {
            "name": "Visible liquidity",
            "formula": "selected scope net + other visible liquid accounts",
            "parts": [_part("Selected scope net", totals["net"]), _part("Other visible accounts", aux)],
            "result": visible,
        },
        {
            "name": "Main available position",
            "formula": "visible liquidity + invested capital",
            "parts": [_part("Visible liquidity", visible), _part("Invested capital", invested)],
            "result": overview["cash_position"],
        },
        {
            "name": "Stress position",
            "formula": "main available position - credit pending - active debts",
            "parts": [
                _part("Main available position", overview["cash_position"]),
                _part("Credit pending", -credit_pending),
                _part("Active debts", -active_debt),
            ],
            "result": overview["stress_position"],
        },
        {
            "name": "Adjusted stress position",
            "formula": "stress position + money owed to me + investment profit/loss",
            "parts": [
                _part("Stress position", overview["stress_position"]),
                _part("Money owed to me", receivable),
                _part("Investment profit/loss", pnl),
            ],
            "result": overview["adjusted_stress_position"],
        },
    ]


def _part(label: str, value: float) -> dict[str, Any]:
    return {"label": label, "value": float(value or 0.0)}


def _excluded_liquid_account_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Rows that are not part of the conservative main-bank net.

    This is intentionally explanatory.  It does not decide balances itself; the
    actual values above come from the existing overview/account services.
    """
    if df.empty:
        return df.copy()
    if "is_auxiliary_account" not in df.columns:
        return df.iloc[0:0].copy()
    excluded = df[df["is_auxiliary_account"].fillna(False)].copy()
    return excluded


def _display_rows(df: pd.DataFrame, *, limit: int) -> list[dict[str, Any]]:
    if df.empty:
        return []
    display = prepare_transactions_for_display(df.head(limit).copy())
    for column in ["category", "sub_category", "account", "account_label", "description", "type"]:
        if column not in display.columns:
            display[column] = ""
        display[column] = display[column].fillna("")
    records = display.to_dict(orient="records")
    for row in records:
        row["signed_amount_str"] = f"{float(row.get('signed_amount', 0.0) or 0.0):.2f}"
        row["account_display"] = row.get("account_label") or row.get("account") or "Selected account"
    return records


def _notes() -> list[str]:
    return [
        "This page is read-only and reuses the same overview calculations already used by the app.",
        "Rows are filtered using the selected account scope when account_id is present.",
        "Linked-wallet payments can appear in both the wallet and the card's funding Conto when the payment method is configured that way.",
    ]


_BALANCE_RELEVANT_FILES = (
    "expenses",
    "incomes",
    "investments",
    "internal_transfers",
    "account_ledger",
    "accounts.json",
    "payment_methods.json",
    "migration_info.json",
)


def _data_source_diagnostics() -> dict[str, Any]:
    """Describe the physical files behind the current authenticated balance.

    A common cross-device failure mode is pulling the code repository while the
    launcher still points at another ``MoneyManagerData`` folder, or pulling on
    top of locally modified data files.  Both cases can leave the visible
    transaction list looking identical while internal transfers or account
    opening/routing data differ.
    """
    from money_manager.config.install_paths import DATA_HOME, PROJECT_ROOT
    from money_manager.config.user_paths import get_current_user_id, get_user_data_dir

    user_id = get_current_user_id()
    try:
        user_dir = get_user_data_dir(user_id) if user_id else None
    except Exception:
        user_dir = None

    project_root = Path(PROJECT_ROOT).resolve()
    data_home = Path(DATA_HOME).resolve()
    default_project_data = (project_root / "MoneyManagerData").resolve()
    sibling_data = (project_root.parent / "MoneyManagerData").resolve()

    file_rows: list[dict[str, Any]] = []
    digest = hashlib.sha256()
    if user_dir:
        for filename in _BALANCE_RELEVANT_FILES:
            path = Path(user_dir) / filename
            row = _file_fingerprint(path, filename, user_id=str(user_id or ""))
            file_rows.append(row)
            digest.update(filename.encode("utf-8"))
            digest.update(str(row.get("content_sha256") or row.get("sha256") or "missing").encode("ascii", errors="ignore"))

    git = _git_diagnostics(project_root, Path(user_dir) if user_dir else None, file_rows)
    alternative_data_homes = []
    for candidate in (default_project_data, sibling_data):
        if candidate == data_home or candidate in alternative_data_homes:
            continue
        if (candidate / "data" / "users").exists():
            alternative_data_homes.append(candidate)

    warnings: list[str] = []
    if data_home != default_project_data:
        warnings.append(
            "This app is not using the MoneyManagerData folder inside the current project. "
            "A Git pull of the project may therefore leave the active financial data unchanged."
        )
    if alternative_data_homes:
        warnings.append(
            "Another MoneyManagerData folder exists near this project. Different launch methods may be opening different copies."
        )
    if git.get("available") and not git.get("data_inside_git"):
        warnings.append("The active user-data folder is outside the Git repository, so pulling main does not update it.")
    if git.get("dirty_files"):
        warnings.append(
            "Balance-related data files have local modifications. Git pull preserves local changes; it does not reset them to origin/main."
        )
    missing = [row["name"] for row in file_rows if not row.get("exists")]
    if missing:
        warnings.append("Some balance-source files are missing: " + ", ".join(missing) + ".")

    return {
        "project_root": str(project_root),
        "data_home": str(data_home),
        "user_dir": str(user_dir or ""),
        "user_id": str(user_id or ""),
        "default_project_data": str(default_project_data),
        "is_default_project_data": data_home == default_project_data,
        "alternative_data_homes": [str(path) for path in alternative_data_homes],
        "dataset_fingerprint": digest.hexdigest()[:20] if file_rows else "",
        "files": file_rows,
        "git": git,
        "warnings": warnings,
    }


def _file_fingerprint(path: Path, filename: str, *, user_id: str = "") -> dict[str, Any]:
    if not path.exists():
        return {"name": filename, "path": str(path), "exists": False, "size": 0, "modified_at": "", "sha256": "", "content_sha256": ""}
    if path.is_dir():
        physical = hashlib.sha256()
        logical = hashlib.sha256()
        total_size = 0
        latest_mtime = 0.0
        errors: list[str] = []
        for child in sorted(item for item in path.rglob("*") if item.is_file()):
            rel = child.relative_to(path).as_posix()
            try:
                raw = child.read_bytes()
                stat = child.stat()
                total_size += int(stat.st_size)
                latest_mtime = max(latest_mtime, stat.st_mtime)
                physical.update(rel.encode("utf-8")); physical.update(raw)
                try:
                    from money_manager.security.secure_storage import secure_read_bytes
                    decrypted = secure_read_bytes(user_id or None, child)
                    logical.update(rel.encode("utf-8")); logical.update(_canonical_content_bytes(child.name, decrypted))
                except Exception as exc:
                    errors.append(f"{rel}: {exc}")
            except Exception as exc:
                errors.append(f"{rel}: {exc}")
        modified = datetime.fromtimestamp(latest_mtime, tz=timezone.utc).isoformat(timespec="seconds") if latest_mtime else ""
        return {
            "name": f"{filename}/",
            "path": str(path),
            "exists": True,
            "size": total_size,
            "modified_at": modified,
            "sha256": physical.hexdigest()[:16],
            "content_sha256": logical.hexdigest()[:16] if not errors else "",
            "content_error": "; ".join(errors[:3]),
        }
    try:
        raw = path.read_bytes()
        stat = path.stat()
        modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(timespec="seconds")
        content_hash = ""
        content_error = ""
        try:
            from money_manager.security.secure_storage import secure_read_bytes

            decrypted = secure_read_bytes(user_id or None, path)
            content_hash = hashlib.sha256(_canonical_content_bytes(filename, decrypted)).hexdigest()[:16]
        except Exception as exc:
            content_error = str(exc)
        return {
            "name": filename,
            "path": str(path),
            "exists": True,
            "size": int(stat.st_size),
            "modified_at": modified,
            "sha256": hashlib.sha256(raw).hexdigest()[:16],
            "content_sha256": content_hash,
            "content_error": content_error,
        }
    except Exception as exc:
        return {
            "name": filename,
            "path": str(path),
            "exists": True,
            "size": 0,
            "modified_at": "",
            "sha256": "",
            "content_sha256": "",
            "error": str(exc),
        }

def _canonical_content_bytes(filename: str, raw: bytes) -> bytes:
    """Hash logical content rather than encryption nonces or formatting."""
    suffix = Path(filename).suffix.casefold()
    if suffix == ".json":
        payload = json.loads(raw.decode("utf-8-sig") or "null")
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    if suffix == ".csv":
        text = raw.decode("utf-8-sig")
        reader = csv.DictReader(StringIO(text))
        rows = [dict(row) for row in reader]
        fields = sorted({str(field) for field in (reader.fieldnames or []) if field} | {str(key) for row in rows for key in row.keys() if key})
        normalized = [{field: str(row.get(field) or "") for field in fields} for row in rows]
        normalized.sort(key=lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        payload = {"fields": fields, "rows": normalized}
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return raw


def _git_diagnostics(project_root: Path, user_dir: Path | None, file_rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "available": False,
        "root": "",
        "branch": "",
        "head": "",
        "data_inside_git": False,
        "tracked_files": [],
        "dirty_files": [],
    }
    try:
        git_root_text = _run_git(project_root, "rev-parse", "--show-toplevel")
        git_root = Path(git_root_text).resolve()
    except Exception:
        return result

    result.update({
        "available": True,
        "root": str(git_root),
        "branch": _run_git_optional(git_root, "rev-parse", "--abbrev-ref", "HEAD"),
        "head": _run_git_optional(git_root, "rev-parse", "--short=12", "HEAD"),
    })
    if not user_dir:
        return result

    try:
        relative_user_dir = user_dir.resolve().relative_to(git_root)
    except ValueError:
        return result

    result["data_inside_git"] = True
    relative_files = []
    for row in file_rows:
        try:
            relative_files.append(str(Path(row["path"]).resolve().relative_to(git_root)).replace(os.sep, "/"))
        except Exception:
            continue

    if relative_files:
        tracked_output = _run_git_optional(git_root, "ls-files", "--", *relative_files)
        result["tracked_files"] = [line.strip() for line in tracked_output.splitlines() if line.strip()]

    status_output = _run_git_optional(git_root, "status", "--porcelain=v1", "--", str(relative_user_dir))
    dirty_files: list[dict[str, str]] = []
    for line in status_output.splitlines():
        if len(line) < 4:
            continue
        dirty_files.append({"status": line[:2], "path": line[3:].strip()})
    result["dirty_files"] = dirty_files
    return result


def _run_git(cwd: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        timeout=2.0,
        check=True,
    )
    return completed.stdout.strip()


def _run_git_optional(cwd: Path, *args: str) -> str:
    try:
        return _run_git(cwd, *args)
    except Exception:
        return ""
