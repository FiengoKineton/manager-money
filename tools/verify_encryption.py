from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from money_manager.security.security_audit_service import verify_user_encryption


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Money Manager encryption status for a user.")
    parser.add_argument("--user", required=True, help="User id to verify")
    args = parser.parse_args()
    report = verify_user_encryption(args.user)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report.get("success") else 2


if __name__ == "__main__":
    raise SystemExit(main())
