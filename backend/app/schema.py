"""Creates the governance tables if they are missing (idempotent, Exasol and DuckDB)."""
from __future__ import annotations

import re

from . import config
from .db import DB, split_statements

GOV_SCHEMA_SQL = config.REPO_ROOT / "db" / "gov_schema.sql"


def _exists(db: DB, table: str) -> bool:
    try:
        db.query(f"SELECT 1 FROM {table} WHERE 1 = 0")
        return True
    except Exception:
        return False


def ensure_gov_schema(db: DB) -> None:
    for statement in split_statements(GOV_SCHEMA_SQL.read_text()):
        m = re.match(r"CREATE\s+TABLE\s+(\S+)", statement, re.I)
        if m and _exists(db, m.group(1)):
            continue
        try:
            db.execute(statement)
        except Exception as exc:  # schema already exists on engines without IF NOT EXISTS
            if "exist" not in str(exc).lower():
                raise
