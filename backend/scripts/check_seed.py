"""Check the planted data after data/seed_signal.py (does not modify anything except the demo report + approval).

    cd backend && python scripts/check_seed.py [--demo]

- PL2: the planted signal is visible with one GROUP BY on the pool (example query from db/pool_schema.md)
- PL3/PL4/DEMO rows are in evals.planted; every planted curated row is labelled origin='seed_signal'
- --demo: runs the M2 exit path for the demo patient through the API (report -> 2 EXPECTED + 1 NEW -> approve ->
  /pool/rare lists blurred vision). This writes a real report and review decision.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("LLM_PROVIDER", "stub")

from app.db import get_db, repo_path  # noqa: E402


def main(argv: list[str]) -> int:
    db = get_db()
    sql = re.search(r"```sql\n(.*?)```", repo_path("db/pool_schema.md").read_text(encoding="utf-8"), re.S).group(1)
    print("PL2 by age band at first Moderna dose (pool views only):")
    for r in db.query(sql):
        rate = 100 * r["n_hypertension"] / r["n_exposed"] if r["n_exposed"] else 0
        print(f"  {r['age_band']:>6}  exposed {r['n_exposed']:4d}  hypertension within 3 months {r['n_hypertension']:3d}"
              f"  ({rate:.1f}%)")
    print("planted:", db.query("SELECT kind, COUNT(*) AS n FROM evals.planted GROUP BY kind ORDER BY kind"))
    print("labelled rows:", db.query(
        "SELECT 'conditions' AS t, origin, COUNT(*) AS n FROM curated.conditions WHERE origin <> 'synthea' GROUP BY origin "
        "UNION ALL SELECT 'immunizations', origin, COUNT(*) FROM curated.immunizations WHERE origin <> 'synthea' "
        "GROUP BY origin UNION ALL SELECT 'reports', origin, COUNT(*) FROM community.reports GROUP BY origin"))
    print("pool.symptom_reports:", db.query(
        "SELECT classification, COUNT(*) AS n FROM pool.symptom_reports GROUP BY classification ORDER BY 1"))

    if "--demo" in argv:
        from fastapi.testclient import TestClient

        from app.main import app

        demo = json.loads(db.query("SELECT description FROM evals.planted WHERE item_id = 'DEMO-1'")[0]["description"])
        with TestClient(app) as c:
            r = c.post(f"/patients/{demo['patient_id']}/reports", json={"text": demo["report_text"], "onset_date": None})
            body = r.json()
            print("demo report:", r.status_code, [(s["term"], s["classification"], s["review_status"])
                                                  for s in body["symptoms"]])
            new = [s for s in body["symptoms"] if s["classification"] == "NEW"]
            for s in new:
                print("approve:", c.post(f"/review/{s['symptom_id']}",
                                         json={"decision": "approve", "reviewer": "Dr. Weber", "note": "demo"}).json())
            print("/pool/rare:", c.get("/pool/rare").json())
            print("/audit/verify:", c.get("/audit/verify").json())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
