"""Creates the tables this service writes if they are missing (idempotent, Exasol and DuckDB)."""
from __future__ import annotations

import re

from . import config
from .db import DB, split_statements

SCHEMA_FILES = [config.REPO_ROOT / "db" / f"{name}_schema.sql" for name in ("gov", "clinical", "community")]


def table_exists(db: DB, table: str) -> bool:
    try:
        db.query(f"SELECT 1 FROM {table} WHERE 1 = 0")
        return True
    except Exception:
        return False


def ensure_schema(db: DB) -> None:
    for path in SCHEMA_FILES:
        for statement in split_statements(path.read_text()):
            m = re.match(r"CREATE\s+TABLE\s+(\S+)", statement, re.I)
            if m and table_exists(db, m.group(1)):
                continue
            try:
                db.execute(statement)
            except Exception as exc:  # schema already exists on engines without IF NOT EXISTS
                if "exist" not in str(exc).lower():
                    raise


ensure_gov_schema = ensure_schema  # M0 name, kept for callers
