from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from money_manager.security.decrypted_export_service import cleanup_expired_decrypted_exports


if __name__ == "__main__":
    print(json.dumps(cleanup_expired_decrypted_exports(), indent=2, ensure_ascii=False))
