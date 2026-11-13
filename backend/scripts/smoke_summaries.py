"""Smoke test on the loaded database: stub summaries for N living patients, both audiences.

    cd backend && python scripts/smoke_summaries.py [N]

Prints every sentence that is not 'verified' with the critic's reasons, then checks inject_error, lineage,
/health and /audit/verify. Exit code 1 if any summary had a problem.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("LLM_PROVIDER", "stub")

from fastapi.testclient import TestClient  # noqa: E402

from app.db import get_db  # noqa: E402
from app.main import app  # noqa: E402


def main(n: int) -> int:
    db = get_db()
    living = [r["patient_id"] for r in db.query(
        "SELECT patient_id FROM curated.patients WHERE death_date IS NULL ORDER BY row_id")]
    step = max(1, len(living) // n)
    pids = living[::step][:n]
    bad = 0
    with TestClient(app) as c:
        for pid in pids:
            for audience in ("patient", "physician"):
                r = c.get(f"/patients/{pid}/summary", params={"audience": audience})
                body = r.json()
                if r.status_code != 200:
                    print(pid, audience, r.status_code, body)
                    bad += 1
                    continue
                sents = [s for sec in body["sections"] for s in sec["sentences"]]
                flagged = [s for s in sents if s["status"] != "verified"]
                if flagged:
                    bad += 1
                    for s in flagged[:3]:
                        print(f"{pid[:8]} {audience:9} {s['text'][:100]!r} -> {s['critic']['reasons']}")
        print(f"summaries with problems: {bad} of {len(pids) * 2}")

        body = c.get(f"/patients/{pids[0]}/summary",
                     params={"audience": "physician", "inject_error": "true", "refresh": "true"}).json()
        print("inject_error ->", body["overall_status"])
        sid = body["sections"][0]["sentences"][0]["sentence_id"]
        print("lineage types:", sorted({x["type"] for x in c.get(f"/lineage/{sid}").json()["chain"]}))
        print("health:", c.get("/health").json())
        print("verify:", c.get("/audit/verify").json())
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 10))
