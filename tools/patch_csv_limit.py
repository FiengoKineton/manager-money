from pathlib import Path

p = Path("money_manager/security/secure_storage.py")
s = p.read_text(encoding="utf-8")

if "import sys" not in s:
    s = s.replace("import csv\n", "import csv\nimport sys\n", 1)

block = '''
def _raise_csv_field_limit() -> None:
    limit = sys.maxsize
    while limit > 10_000_000:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10
    csv.field_size_limit(10_000_000)


_raise_csv_field_limit()

'''

if "_raise_csv_field_limit" not in s:
    lines = s.splitlines(True)

    insert_at = 0
    for i, line in enumerate(lines):
        if line.startswith("import ") or line.startswith("from "):
            insert_at = i + 1

    while insert_at < len(lines) and lines[insert_at].strip() == "":
        insert_at += 1

    lines.insert(insert_at, block)
    s = "".join(lines)

p.write_text(s, encoding="utf-8")
print("Patched:", p)
