"""DEV-ONLY app so the research engine runs before Dev B's app/main.py exists.

    cd backend && uvicorn app.research.devapp:app --reload --port 8000

Serves the research router plus thin dev versions of /health, /audit, /audit/verify and /lineage/{id} built on the
same fallbacks as deps.py. Once Dev B's main.py is merged, run that instead and include `app.routes.research.router`.
"""
from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.research import deps, store
from app.routes import research

app = FastAPI(title="TrustLens (research dev server)", version="0.1-dev")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(research.router)


@app.get("/health", tags=["system"])
def health():
    db = deps.get_db()
    store.ensure_schema(db)

    def count(table: str) -> int:
        return db.query(f"SELECT COUNT(*) AS n FROM {table}")[0]["n"] if deps.table_exists(db, table) else 0

    return {"status": "ok", "db": getattr(db, "dialect", "duckdb"), "llm": deps.llm_provider(),
            "counts": {"patients": count("pool.patients"), "papers": count("research.papers")}, "server": "research-dev"}


@app.get("/audit", tags=["governance"])
def audit(limit: int = 100):
    rows = deps.get_db().query("SELECT * FROM gov.audit_events ORDER BY seq DESC LIMIT ?", [limit])
    return [dict({k: v for k, v in r.items() if k != "payload_json"}, payload=json.loads(r["payload_json"] or "{}"))
            for r in rows]


@app.get("/audit/verify", tags=["governance"])
def audit_verify():
    return deps.audit_verify()


@app.get("/lineage/{item_id}", tags=["governance"])
def lineage(item_id: str):
    return {"id": item_id, "type": None, "chain": deps.lineage_chain(item_id), "producer": None}
