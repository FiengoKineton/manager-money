from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from money_manager.services.update_service import apply_pending_update_from_launcher


def main() -> int:
    try:
        result = apply_pending_update_from_launcher()
    except Exception as exc:  # launcher should keep starting the old app when safe
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
