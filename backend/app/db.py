"""Database access (interface from docs/context/01-dev-a-data.md §6). Owned by Dev A; M0 version by Dev B.

    db = get_db()                          # Exasol if EXASOL_DSN is set, else DuckDB (data/trustlens.duckdb)
    db.query(sql, params=None) -> list[dict]   # lowercase column names
    db.execute(sql, params=None) -> None
    db.insert_rows(table, rows: list[dict])
    db.insert_df(table, df)                # bulk path used by the loader
    db.run_script(path)                    # runs a .sql file (statements split on ';')
    DB.named_blocks(path) -> dict[str, str]    # parses '-- name: x' blocks
    db.dialect -> "exasol" | "duckdb"

Parameters: positional `?` with a list/tuple, or named `:name` with a dict. Not both in one statement.

Portability rules for SQL in this repo:
- Lowercase, unquoted identifiers. Exasol uppercases them; result keys come back lowercase on both engines.
- Contract names that are reserved words in Exasol (EXASOL_QUOTED) are quoted automatically on Exasol,
  so `SELECT text FROM ref.lab_ranges` works on both. Outside this module, quote them yourself ("TEXT", "REF").
- Exasol treats '' as NULL and `'a' || NULL` is 'a' (DuckDB: NULL). Use CASE, not COALESCE(x || y, ...).
- `date - date` (days) and `date + n` work on both. Avoid vendor functions.
- DECIMAL values come back as int/float on both engines (never Decimal).

CLI (from backend/):  python -m app.db check  |  python -m app.db run <file.sql>
"""
from __future__ import annotations

import datetime as _dt
import decimal
import json
import math
import os
import re
import threading
from pathlib import Path
from typing import Any

from . import config

# Contract identifiers that are reserved words in Exasol (checked against Exasol's keyword list).
EXASOL_QUOTED = frozenset({"ref", "text", "section", "state", "low", "high", "transform"})
_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def repo_path(p: str | os.PathLike) -> Path:
    path = Path(p)
    return path if path.is_absolute() else config.REPO_ROOT / path


# ---------- SQL text helpers ----------
def _scan(sql: str):
    """Yield (kind, text) tokens: 'code', 'str' ('...'), 'ident' ("..."), 'comment'."""
    i, n, start = 0, len(sql), 0
    while i < n:
        c = sql[i]
        if c in ("'", '"'):
            if start < i:
                yield "code", sql[start:i]
            j = i + 1
            while j < n:
                if sql[j] == c:
                    if j + 1 < n and sql[j + 1] == c:  # doubled quote = escaped
                        j += 2
                        continue
                    break
                j += 1
            yield ("str" if c == "'" else "ident"), sql[i:j + 1]
            i = start = j + 1
        elif sql.startswith("--", i) or sql.startswith("/*", i):
            if start < i:
                yield "code", sql[start:i]
            if sql.startswith("--", i):
                j = sql.find("\n", i)
                j = n if j == -1 else j
            else:
                j = sql.find("*/", i + 2)
                j = n if j == -1 else j + 2
            yield "comment", sql[i:j]
            i = start = j
        else:
            i += 1
    if start < n:
        yield "code", sql[start:n]


def split_statements(sql: str) -> list[str]:
    """Split a script on ';' outside strings and comments. Comment-only pieces are dropped."""
    out, buf, has_code = [], [], False
    for kind, tok in _scan(sql):
        if kind != "code":
            if kind != "comment":
                buf.append(tok)
                has_code = True
            continue
        parts = tok.split(";")
        for k, part in enumerate(parts):
            buf.append(part)
            has_code = has_code or bool(part.strip())
            if k < len(parts) - 1:
                if has_code:
                    out.append("".join(buf).strip())
                buf, has_code = [], False
    if has_code:
        out.append("".join(buf).strip())
    return out


def _normalise(v: Any) -> Any:
    if isinstance(v, decimal.Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


def _prepare_value(v: Any) -> Any:
    return json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v


def lit(value: Any) -> str:
    """SQL literal for the rare place a placeholder can't be used (and for inlining params on Exasol)."""
    value = _prepare_value(value)
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, decimal.Decimal)):
        return str(value)
    if isinstance(value, float):
        return "NULL" if math.isnan(value) else repr(value)
    if isinstance(value, _dt.datetime):
        return "TIMESTAMP '" + value.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] + "'"
    if isinstance(value, _dt.date):
        return "DATE '" + value.isoformat() + "'"
    return "'" + str(value).replace("'", "''") + "'"


# ---------- base ----------
class DB:
    dialect: str

    def query(self, sql: str, params: Any = None) -> list[dict]:
        raise NotImplementedError

    def execute(self, sql: str, params: Any = None) -> None:
        raise NotImplementedError

    def insert_rows(self, table: str, rows: list[dict]) -> None:
        if not rows:
            return
        cols = list(rows[0].keys())
        sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})"
        for row in rows:
            self.execute(sql, [_prepare_value(row.get(c)) for c in cols])

    def insert_df(self, table: str, df) -> None:
        self.insert_rows(table, df.to_dict("records"))

    def run_script(self, path: str | Path) -> None:
        for statement in split_statements(repo_path(path).read_text(encoding="utf-8")):
            self.execute(statement)

    @staticmethod
    def named_blocks(path: str | Path) -> dict[str, str]:
        """Parse '-- name: x' blocks from a .sql file. Each block runs to the next marker; trailing ';' removed."""
        blocks: dict[str, list[str]] = {}
        name = None
        for line in repo_path(path).read_text(encoding="utf-8").splitlines():
            m = re.match(r"^\s*--\s*name:\s*([A-Za-z_]\w*)\s*$", line)
            if m:
                name = m.group(1)
                blocks[name] = []
            elif name:
                blocks[name].append(line)
        out = {}
        for k, lines in blocks.items():
            body = "\n".join(lines).strip()
            while body.endswith(";"):
                body = body[:-1].rstrip()
            out[k] = body
        return out

    def close(self) -> None:
        pass


# ---------- DuckDB ----------
class DuckDB(DB):
    dialect = "duckdb"

    def __init__(self, path: str):
        import duckdb

        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(path)
        self._lock = threading.RLock()

    @staticmethod
    def _bind(sql: str, params: Any) -> tuple[str, Any]:
        """`:name` -> `$name` for dict params (only the referenced names are passed; `::` casts untouched)."""
        if not isinstance(params, dict):
            return sql, list(params) if params else []
        used: set[str] = set()

        def sub(m: re.Match) -> str:
            used.add(m.group(1))
            return "$" + m.group(1)

        out = [re.sub(r"(?<![:\w]):([A-Za-z_]\w*)", sub, tok) if kind == "code" else tok
               for kind, tok in _scan(sql)]
        missing = used - params.keys()
        if missing:
            raise KeyError(f"missing SQL parameter(s): {sorted(missing)}")
        return "".join(out), {k: v for k, v in params.items() if k in used}

    def query(self, sql, params=None):
        q, p = self._bind(sql, params)
        with self._lock:
            cur = self._conn.execute(q, p) if p else self._conn.execute(q)
            if cur.description is None:
                return []
            cols = [d[0].lower() for d in cur.description]
            return [{c: _normalise(v) for c, v in zip(cols, row)} for row in cur.fetchall()]

    def execute(self, sql, params=None):
        q, p = self._bind(sql, params)
        with self._lock:
            if p:
                self._conn.execute(q, p)
            else:
                self._conn.execute(q)

    def insert_rows(self, table, rows):
        if not rows:
            return
        cols = list(rows[0].keys())
        sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})"
        with self._lock:
            self._conn.executemany(sql, [[_prepare_value(r.get(c)) for c in cols] for r in rows])

    def insert_df(self, table, df):
        if len(df) == 0:
            return
        cols = ", ".join(df.columns)
        with self._lock:
            self._conn.register("_tl_insert_df", df)
            try:
                self._conn.execute(f"INSERT INTO {table} ({cols}) SELECT {cols} FROM _tl_insert_df")
            finally:
                self._conn.unregister("_tl_insert_df")

    def close(self):
        with self._lock:
            self._conn.close()


# ---------- Exasol ----------
class Exasol(DB):
    dialect = "exasol"

    def __init__(self, dsn: str, user: str, password: str):
        import pyexasol

        opts: dict[str, Any] = dict(dsn=dsn, user=user, password=password, compression=True, encryption=True,
                                    fetch_dict=True, lower_ident=True, fetch_mapper=pyexasol.exasol_mapper,
                                    quote_ident=True)  # import_from_* gets exact uppercase names from us
        # Exasol Personal uses a self-signed certificate. Preferred: certificate fingerprint in the DSN
        # (host/FINGERPRINT:8563). Otherwise EXASOL_SSL_VERIFY=false turns verification off.
        if os.getenv("EXASOL_SSL_VERIFY", "true").lower() in ("0", "false", "no"):
            import ssl

            opts["websocket_sslopt"] = {"cert_reqs": ssl.CERT_NONE}
        self._conn = pyexasol.connect(**opts)
        self._lock = threading.RLock()
        # DATE/TIMESTAMP <-> VARCHAR use the same ISO text as DuckDB
        self._conn.execute("ALTER SESSION SET NLS_DATE_FORMAT = 'YYYY-MM-DD'")
        self._conn.execute("ALTER SESSION SET NLS_TIMESTAMP_FORMAT = 'YYYY-MM-DD HH24:MI:SS.FF3'")

    @staticmethod
    def _bind(sql: str, params: Any) -> str:
        """Inline params as escaped literals and quote Exasol-reserved contract names."""
        positional = list(params) if isinstance(params, (list, tuple)) else None
        named = params if isinstance(params, dict) else None
        pos, out = 0, []
        for kind, tok in _scan(sql):
            if kind != "code":
                out.append(tok)
                continue
            res, i = [], 0
            while i < len(tok):
                c = tok[i]
                prev = tok[i - 1] if i else ""
                if c == "?" and positional is not None:
                    if pos >= len(positional):
                        raise ValueError("not enough positional parameters")
                    res.append(lit(positional[pos]))
                    pos += 1
                    i += 1
                elif c == ":" and named is not None and prev != ":" and _NAME_RE.match(tok, i + 1):
                    m = _NAME_RE.match(tok, i + 1)
                    if m.group(0) not in named:
                        raise KeyError(f"missing SQL parameter :{m.group(0)}")
                    res.append(lit(named[m.group(0)]))
                    i = m.end()
                elif c.isalpha() or c == "_":
                    m = _NAME_RE.match(tok, i)
                    word = m.group(0)
                    quote = word.lower() in EXASOL_QUOTED and not (prev.isalnum() or prev in "_$")
                    res.append(f'"{word.upper()}"' if quote else word)
                    i = m.end()
                else:
                    res.append(c)
                    i += 1
            out.append("".join(res))
        if positional is not None and pos != len(positional):
            raise ValueError("too many positional parameters")
        return "".join(out)

    def query(self, sql, params=None):
        with self._lock:
            stmt = self._conn.execute(self._bind(sql, params))
            if stmt.result_type != "resultSet":
                return []
            return [{k.lower(): _normalise(v) for k, v in row.items()} for row in stmt.fetchall()]

    def execute(self, sql, params=None):
        with self._lock:
            self._conn.execute(self._bind(sql, params))

    def insert_rows(self, table, rows, batch: int = 500):
        if not rows:
            return
        cols = list(rows[0].keys())
        head = f"INSERT INTO {table} ({', '.join(cols)}) VALUES "
        for k in range(0, len(rows), batch):
            self.execute(head + ", ".join(
                "(" + ", ".join(lit(r.get(c)) for c in cols) + ")" for r in rows[k:k + batch]))

    def insert_df(self, table, df):
        if len(df) == 0:
            return
        import pandas as pd

        out = df.copy()
        for col in out.columns:
            s = out[col]
            if pd.api.types.is_datetime64_any_dtype(s):
                out[col] = s.dt.strftime("%Y-%m-%d %H:%M:%S.%f").str[:-3].where(s.notna(), None)
        schema, name = table.split(".")
        with self._lock:
            self._conn.import_from_pandas(out, (schema.upper(), name.upper()),
                                          import_params={"columns": [c.upper() for c in out.columns]})

    def close(self):
        with self._lock:
            self._conn.close()


# ---------- factory ----------
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


def _main(argv: list[str]) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="python -m app.db")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="connect and print dialect, server time, patient count")
    run = sub.add_parser("run", help="run a .sql script")
    run.add_argument("path")
    args = ap.parse_args(argv)
    db = get_db()
    if args.cmd == "check":
        now = db.query("SELECT CURRENT_TIMESTAMP AS now_ts")[0]["now_ts"]
        print(f"dialect={db.dialect} now={now} patients={table_count(db, 'curated.patients')}")
    else:
        db.run_script(args.path)
        print(f"ran {args.path} on {db.dialect}")
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(_main(sys.argv[1:]))
