"""Run db/pool_queries.sql:exposure_outcome_rate for a few exposure/outcome pairs and print the rates.

    cd backend && python scripts/check_exposure_rate.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import get_db  # noqa: E402

PAIRS = [
    ("207", "59621000", 90, "Moderna -> hypertension (planted PL2 signal)"),
    ("208", "59621000", 90, "Pfizer -> hypertension (no signal planted)"),
    ("207", "44054006", 90, "Moderna -> type 2 diabetes (no signal planted)"),
    ("999", "59621000", 90, "unknown exposure"),
]


def main() -> int:
    db = get_db()
    sql = db.named_blocks("db/pool_queries.sql")["exposure_outcome_rate"]
    for exp, out, days, label in PAIRS:
        r = db.query(sql, {"exposure_code": exp, "outcome_code": out, "window_days": days})[0]
        er = 100 * r["n_outcome_exposed"] / r["n_exposed"] if r["n_exposed"] else None
        br = 100 * r["n_outcome_unexposed"] / r["n_unexposed"] if r["n_unexposed"] else None
        fmt = lambda v: "n/a" if v is None else f"{v:.1f}%"  # noqa: E731
        print(f"{label:<48} exposed {r['n_outcome_exposed']:>3}/{r['n_exposed']:<4} {fmt(er):>6}   "
              f"unexposed {r['n_outcome_unexposed']:>3}/{r['n_unexposed']:<4} {fmt(br):>6}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
