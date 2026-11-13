"""Check db/pool_schema.md against the loaded database.

    cd backend && python scripts/check_pool_schema.py

- every view/column listed in the table exists, and nothing else does
- every code in "Codes present in the data" is really in the named view
- the example query runs
Exit code 1 on any mismatch.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import get_db, repo_path  # noqa: E402


def main() -> int:
    db = get_db()
    text = repo_path("db/pool_schema.md").read_text(encoding="utf-8")
    ok = True

    documented = {m[0]: [c.strip() for c in m[1].split(",")]
                  for m in re.findall(r"\| `pool\.(\w+)` \| `([^`]+)` \|", text)}
    for view, cols in documented.items():
        try:
            actual_cols = _columns(db, view)
        except Exception as e:  # noqa: BLE001
            print(f"FAIL pool.{view}: {e}")
            ok = False
            continue
        status = "ok" if actual_cols == cols else f"MISMATCH actual={actual_cols}"
        ok = ok and actual_cols == cols
        print(f"view pool.{view:<16} {status}")

    for label, system, code, view in re.findall(r"\| ([^|]+?) \| (\w+) `([^`]+)`[^|]*\| `pool\.(\w+)` \|", text):
        n = db.query(f"SELECT COUNT(*) AS n FROM pool.{view} WHERE concept_code = ?", [code])[0]["n"]
        ok = ok and n > 0
        print(f"code {system} {code:<10} {label:<35} rows={n}{'' if n else '  MISSING'}")

    sql = re.search(r"```sql\n(.*?)```", text, re.S).group(1)
    rows = db.query(sql)
    print("example query:", rows)
    return 0 if ok else 1


def _columns(db, view: str) -> list[str]:
    if db.dialect == "duckdb":
        return [r["column_name"] for r in db.query(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = 'pool' AND table_name = ? "
            "ORDER BY ordinal_position", [view])]
    return [r["column_name"].lower() for r in db.query(
        "SELECT column_name FROM exa_all_columns WHERE column_schema = 'POOL' AND column_table = ? "
        "ORDER BY column_ordinal_position", [view.upper()])]


if __name__ == "__main__":
    sys.exit(main())
