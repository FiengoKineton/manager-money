#!/usr/bin/env python3
"""Read-only audit for legacy one-Conto/main-net assumptions."""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

SCAN_SUFFIXES = {".py", ".html", ".json", ".md"}
IGNORE_DIRS = {".git", ".hg", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", ".venv", "venv", "__pycache__", "cache", "backups", "node_modules", "MoneyManagerData"}

PATTERNS: dict[str, list[str]] = {
    "direct MAIN_ACCOUNT_KEY use": ["MAIN_ACCOUNT_KEY"],
    'direct "main_bank" string use': ['"main_bank"', "'main_bank'"],
    "main_account_transactions": ["main_account_transactions"],
    "main_net naming": ["main_net", "Main Net", "main net"],
    "main_pending_total": ["main_pending_total"],
    "auxiliary_account_keys": ["auxiliary_account_keys"],
    "auxiliary_total": ["auxiliary_total"],
    "affects_main_net": ["affects_main_net"],
    "unsafe template main labels": ["Main available", "main available", "Main net", "main net"],
    "payables/pending main-only check": ["normalize_account_key(account_id) == MAIN_ACCOUNT_KEY", "== MAIN_ACCOUNT_KEY"],
}

ALLOWED_WRAPPER_FILES = {
    Path("money_manager/services/account_service.py"),
    Path("money_manager/config/__init__.py"),
    Path("money_manager/config/user_defaults.py"),
    Path("docs/account_scope_model.md"),
}
MIGRATION_FILES = {Path("money_manager/services/schema_service.py"), Path("money_manager/services/account_config_service.py"), Path("money_manager/services/payment_method_service.py"), Path("money_manager/config/user_defaults.py")}


@dataclass(frozen=True)
class Match:
    path: Path
    line_no: int
    category: str
    phrase: str
    line: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit account/payment legacy usage.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--context", type=int, default=0)
    parser.add_argument("--max-line-length", type=int, default=220)
    return parser.parse_args()


def should_scan(path: Path) -> bool:
    if path.suffix.lower() not in SCAN_SUFFIXES:
        return False
    return not any(part in IGNORE_DIRS for part in path.parts)


def iter_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if path.is_file() and should_scan(path.relative_to(root)):
            yield path


def find_matches(line: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    lower = line.casefold()
    for category, phrases in PATTERNS.items():
        for phrase in phrases:
            if phrase.casefold() in lower:
                found.append((category, phrase))
                break
    return found


def classify(match: Match) -> str:
    path = match.path
    text = f"{match.line} {match.path}".casefold()
    if path in ALLOWED_WRAPPER_FILES and any(token in text for token in ["compat", "legacy", "default", "wrapper", "main_bank"]):
        return "allowed compatibility wrappers/defaults"
    if path in MIGRATION_FILES or "migration" in text or "deprecated" in text:
        return "migration/default data references"
    if path.suffix == ".html" or "template" in str(path):
        return "unsafe template naming"
    if any(part in {"services", "repositories", "web"} for part in path.parts):
        return "unsafe service/route logic"
    return "other references"


def scan_file(path: Path, root: Path) -> tuple[list[str], list[Match]]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return [], []
    rel = path.relative_to(root)
    matches: list[Match] = []
    for line_no, line in enumerate(lines, start=1):
        for category, phrase in find_matches(line):
            matches.append(Match(rel, line_no, category, phrase, line.strip()))
    return lines, matches


def trim(text: str, max_len: int) -> str:
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


def main() -> int:
    args = parse_args()
    root = Path(args.root).expanduser().resolve()
    if not root.exists():
        raise SystemExit(f"Root does not exist: {root}")

    grouped_by_class: dict[str, list[Match]] = defaultdict(list)
    grouped_by_category: dict[str, list[Match]] = defaultdict(list)
    grouped_by_file: dict[Path, list[Match]] = defaultdict(list)
    file_lines: dict[Path, list[str]] = {}

    for path in iter_files(root):
        lines, matches = scan_file(path, root)
        if not matches:
            continue
        rel = path.relative_to(root)
        file_lines[rel] = lines
        for match in matches:
            grouped_by_file[rel].append(match)
            grouped_by_category[match.category].append(match)
            grouped_by_class[classify(match)].append(match)

    print("Scoped account/payment audit report")
    print(f"Root: {root}")
    print(f"Files with matches: {len(grouped_by_file)}")
    print(f"Total matches: {sum(len(items) for items in grouped_by_file.values())}")
    print()

    for class_name in ["unsafe service/route logic", "unsafe template naming", "allowed compatibility wrappers/defaults", "migration/default data references", "other references"]:
        items = grouped_by_class.get(class_name, [])
        print(f"## {class_name}: {len(items)}")
        by_cat: dict[str, int] = defaultdict(int)
        for item in items:
            by_cat[item.category] += 1
        for category in sorted(by_cat):
            print(f"- {category}: {by_cat[category]}")
        print()

    print("Matches by file")
    for rel in sorted(grouped_by_file):
        matches = grouped_by_file[rel]
        print(f"\n## {rel} ({len(matches)} matches)")
        lines = file_lines.get(rel, [])
        seen_context_lines: set[int] = set()
        for match in matches:
            label = classify(match)
            if args.context <= 0:
                print(f"{match.line_no}: [{label} / {match.category}] {trim(match.line, args.max_line_length)}")
                continue
            start = max(1, match.line_no - args.context)
            end = min(len(lines), match.line_no + args.context)
            for line_no in range(start, end + 1):
                if line_no in seen_context_lines:
                    continue
                seen_context_lines.add(line_no)
                marker = ">" if line_no == match.line_no else " "
                source_line = lines[line_no - 1].rstrip()
                print(f"{marker}{line_no}: {trim(source_line, args.max_line_length)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
