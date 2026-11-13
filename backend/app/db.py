"""Database access (interface from docs/context/01-dev-a-data.md §6).

Minimal version written by Dev B for M0 so audit/lineage can run. Dev A owns this file
from here on and may extend it; keep the public interface stable.

Exasol when EXASOL_DSN is set, otherwise a local DuckDB file.
SQL uses `?` placeholders; they are translated for pyexasol.
"""
from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Any

from . import config


class DB:
    dialect: str

    def query(self, sql: str, params: list | tuple | None = None) -> list[dict]:
        raise NotImplementedError

    def execute(self, sql: str, params: list | tuple | None = None) -> None:
        raise NotImplementedError

    def insert_rows(self, table: str, rows: list[dict]) -> None:
        if not rows:
            return
        cols = list(rows[0].keys())
        sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})"
        for row in rows:
            self.execute(sql, [row[c] for c in cols])

    def run_script(self, path: str | Path) -> None:
        for statement in split_statements(Path(path).read_text()):
            self.execute(statement)

    @staticmethod
    def named_blocks(path: str | Path) -> dict[str, str]:
        """Parse '-- name: x' blocks from a .sql file."""
        blocks: dict[str, str] = {}
        name, lines = None, []
        for line in Path(path).read_text().splitlines():
            m = re.match(r"--\s*name:\s*(\S+)", line)
            if m:
                if name:
                    blocks[name] = "\n".join(lines).strip().rstrip(";")
                name, lines = m.group(1), []
            elif name:
                lines.append(line)
        if name:
            blocks[name] = "\n".join(lines).strip().rstrip(";")
        return blocks


def split_statements(sql: str) -> list[str]:
    no_comments = "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--"))
    return [s.strip() for s in no_comments.split(";") if s.strip()]


class DuckDB(DB):
    dialect = "duckdb"

    def __init__(self, path: str):
        import duckdb

        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(path)
        self._lock = threading.Lock()

    def query(self, sql, params=None):
        with self._lock:
            cur = self._conn.execute(sql, params or [])
            cols = [d[0].lower() for d in cur.description] if cur.description else []
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def execute(self, sql, params=None):
        with self._lock:
            self._conn.execute(sql, params or [])


class Exasol(DB):
    dialect = "exasol"

    def __init__(self, dsn: str, user: str, password: str):
        import pyexasol

        self._conn = pyexasol.connect(dsn=dsn, user=user, password=password, compression=True)
        self._lock = threading.Lock()

    @staticmethod
    def _bind(sql: str, params) -> tuple[str, dict]:
        if not params:
            return sql, {}
        out, values, i = [], {}, 0
        for part in re.split(r"(\?)", sql):
            if part == "?":
                key = f"p{i}"
                out.append("{" + key + "}")
                values[key] = params[i]
                i += 1
            else:
                out.append(part.replace("{", "{{").replace("}", "}}"))
        return "".join(out), values

    def query(self, sql, params=None):
        q, values = self._bind(sql, params)
        with self._lock:
            stmt = self._conn.execute(q, values)
            cols = [c.lower() for c in stmt.column_names()]
            return [dict(zip(cols, row)) for row in stmt.fetchall()]

    def execute(self, sql, params=None):
        q, values = self._bind(sql, params)
        with self._lock:
            self._conn.execute(q, values)


_db: DB | None = None
_db_lock = threading.Lock()


def get_db() -> DB:
    global _db
    with _db_lock:
        if _db is None:
            if config.EXASOL_DSN:
                _db = Exasol(config.EXASOL_DSN, config.EXASOL_USER, config.EXASOL_PASSWORD)
            else:
                _db = DuckDB(config.DUCKDB_PATH)
        return _db


def set_db(db: DB | None) -> None:
    """Swap the connection (tests use an in-memory DuckDB)."""
    global _db
    with _db_lock:
        _db = db


def table_count(db: DB, table: str) -> int | None:
    try:
        return int(db.query(f"SELECT COUNT(*) AS n FROM {table}")[0]["n"])
    except Exception:
        return None


def lit(value: Any) -> str:
    """SQL literal for the rare place a placeholder can't be used."""
    if value is None:
        return "NULL"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"
