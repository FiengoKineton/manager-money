from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from money_manager.config.user_paths import using_user
from money_manager.services.account_ledger_service import rebuild_ledger_from_transactions
from money_manager.services.schema_service import ensure_user_schema


def main() -> int:
    parser = argparse.ArgumentParser(description="Preview or rebuild account_ledger.csv from existing transaction CSVs.")
    parser.add_argument("--user", required=True, help="User id under data/users/{user_id}.")
    parser.add_argument("--write", action="store_true", help="Actually append inferred ledger rows. Default is dry-run preview.")
    parser.add_argument("--json", action="store_true", help="Print the full report as JSON.")
    args = parser.parse_args()

    with using_user(args.user):
        ensure_user_schema(args.user)
        report = rebuild_ledger_from_transactions(dry_run=not args.write, user_id=args.user)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        mode = "WRITE" if args.write else "DRY RUN"
        print(f"Ledger rebuild preview ({mode}) for user {args.user}")
        print(f"Inferred movements: {report.get('inferred_movement_count', 0)}")
        print(f"Skipped transactions: {report.get('skipped_count', 0)}")
        if report.get("skipped"):
            print("First skipped examples:")
            for item in report["skipped"][:10]:
                print(f"- {item.get('transaction_type')}:{item.get('id')} -> {item.get('reason')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
