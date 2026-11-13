"""Shared helpers for the research engine: schema, IDs, timestamps, JSON."""
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path

from app.research import deps

SCHEMA_FILE = Path(__file__).parent / "sql" / "schema.sql"
_schema_ready: set[int] = set()


def ensure_schema(db=None) -> None:
    """Create research.* tables if missing. Idempotent; statements run one by one so it works on Exasol too."""
    db = db or deps.get_db()
    if id(db) in _schema_ready:
        return
    for stmt in split_sql(SCHEMA_FILE.read_text()):
        db.execute(stmt)
    _schema_ready.add(id(db))


def split_sql(text: str) -> list[str]:
    """Drop '--' comment lines, then split on ';'. Good enough for our DDL files (no ';' inside strings)."""
    body = "\n".join(ln for ln in text.splitlines() if not ln.strip().startswith("--"))
    return [s.strip() for s in body.split(";") if s.strip()]


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def run_id(prefix: str) -> str:
    """Time-sortable run ID, e.g. KG-20261113-143012-a1b2."""
    return f"{prefix}-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"


def short_hash(*parts: str, n: int = 10) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:n]


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)


def loads(text, default=None):
    if text is None or text == "":
        return default
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return default
