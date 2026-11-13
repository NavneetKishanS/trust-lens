"""Prepare a database for the local UI (called by ./start.sh; safe to run again).

    python scripts/dev_setup.py           # print "real" or "demo": is real Synthea data loaded in the default DB?
    python scripts/dev_setup.py prepare   # make sure the DB in DUCKDB_PATH / EXASOL_DSN is ready for the UI

prepare:
  * real data (curated.patients has Synthea rows): only adds what the research screens need and is missing
    (papers from the Europe PMC cache or the API, and a knowledge-graph build). Never touches curated.* or pool.*.
  * demo mode (no real data): 3 dev-fixture patients (app.devdata) + the dev stand-in pool (app.research.devpool,
    1,000 synthetic pseudonymous patients with a planted PL2-style signal), then papers + graph.
Everything is synthetic. The planted hypertension signal is not a finding about any real vaccine.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT / "backend")

REAL_MIN_PATIENTS = 50


def count(db, table: str) -> int:
    from app.db import table_count

    return table_count(db, table) or 0


def detect() -> str:
    from app.db import get_db

    return "real" if count(get_db(), "curated.patients") >= REAL_MIN_PATIENTS else "demo"


def prepare() -> None:
    from app.db import get_db
    from app.schema import ensure_gov_schema

    db = get_db()
    ensure_gov_schema(db)
    real = count(db, "curated.patients") >= REAL_MIN_PATIENTS
    print(f"[setup] database: {db.dialect} · {'real Synthea data' if real else 'local demo data'}")

    if not real:
        from app import devdata
        from app.research import devpool

        if devdata.load():
            print("[setup] added 3 dev-fixture patients (origin='dev_fixture')")
        if count(db, "pool.patients") == 0:
            print("[setup] creating the dev stand-in pool (1,000 synthetic patients, planted signal) ...")
            print(f"[setup] {devpool.create(db, force=True)}")

    from app.research import graph, papers

    if count(db, "research.papers") == 0:
        cache = ROOT / "data" / "papers"
        offline = cache.exists() and any(cache.rglob("search-*.json"))
        print(f"[setup] loading papers ({'from the local cache' if offline else 'from Europe PMC, takes ~2 min'}) ...")
        print(f"[setup] {papers.ingest('covid_vaccine_safety', offline=offline)}")
    if count(db, "research.edges") == 0:
        print("[setup] building the knowledge graph (stub agents, with the PL5 fabricated-quote test) ...")
        print(f"[setup] {graph.build('covid_vaccine_safety', max_papers=200, inject_fabricated_quote=True)}")
    print("[setup] ready")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "prepare":
        prepare()
    else:
        print(detect())
