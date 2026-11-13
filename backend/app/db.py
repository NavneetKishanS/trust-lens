"""Database access for TrustLens (Dev A).

One small interface over Exasol (when EXASOL_DSN is set) or a local DuckDB file (default):

    db = get_db()
    db.query(sql, params=None) -> list[dict]      # lowercase column names
    db.execute(sql, params=None) -> None
    db.insert_rows(table, rows: list[dict]) -> None
    db.insert_df(table, df) -> None               # bulk path used by the loader
    db.run_script(path) -> None                   # runs a .sql file (statements split on ';')
    db.named_blocks(path) -> dict[str, str]       # parses '-- name: x' blocks
    db.dialect -> "exasol" | "duckdb"

Parameters: either positional `?` with a list/tuple, or named `:name` with a dict. Never both.

Portability notes for anyone writing SQL against this:
- Write lowercase, unqualified-by-quotes identifiers. Exasol uppercases them; we lowercase result keys.
- A few contract names are reserved words in Exasol (see EXASOL_QUOTED). This module wraps them in
  double quotes automatically on Exasol, so `SELECT text FROM ref.lab_ranges` works on both databases.
  If you bypass this module, quote them yourself: "TEXT", "REF", ...
- In Exasol the empty string is NULL and `'a' || NULL` is 'a' (DuckDB gives NULL). Use CASE, not COALESCE(x || y, ...).
- Dates: `date - date` = days and `date + n` = date work on both. Avoid vendor functions; branch on db.dialect in one place.

CLI:  python -m app.db check            # which DB, can we connect
      python -m app.db run <file.sql>   # run a script (e.g. scripts/tamper.sql)
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
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]

try:  # optional: load the repo's .env so every entry point sees the same settings
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
except ImportError:  # pragma: no cover
    pass

# Contract identifiers that are reserved words in Exasol (checked against Exasol's keyword list).
EXASOL_QUOTED = frozenset({"ref", "text", "section", "state", "low", "high", "transform"})

_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def repo_path(p: str | os.PathLike) -> Path:
    """Resolve a path relative to the repo root (env vars hold repo-relative paths)."""
    path = Path(p)
    return path if path.is_absolute() else REPO_ROOT / path


# --------------------------------------------------------------------------------------------
# SQL text helpers (shared by both dialects)
# --------------------------------------------------------------------------------------------

def _scan(sql: str):
    """Yield (kind, text) tokens: 'code', 'str' ('...'), 'ident' ("..."), 'comment'."""
    i, n, start = 0, len(sql), 0
    while i < n:
        c = sql[i]
        if c == "'" or c == '"':
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
            yield ("str" if c == "'" else "ident"), sql[i : j + 1]
            i = start = j + 1
        elif sql.startswith("--", i):
            if start < i:
                yield "code", sql[start:i]
            j = sql.find("\n", i)
            j = n if j == -1 else j
            yield "comment", sql[i:j]
            i = start = j
        elif sql.startswith("/*", i):
            if start < i:
                yield "code", sql[start:i]
            j = sql.find("*/", i + 2)
            j = n if j == -1 else j + 2
            yield "comment", sql[i:j]
            i = start = j
        else:
            i += 1
    if start < n:
        yield "code", sql[start:n]


def split_statements(script: str) -> list[str]:
    """Split a script on ';' outside strings and comments. Comment-only statements are dropped."""
    out, buf, has_code = [], [], False
    for kind, tok in _scan(script):
        if kind != "code":
            buf.append(tok)
            has_code = has_code or kind in ("str", "ident")
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


def parse_named_blocks(text: str) -> dict[str, str]:
    """Parse '-- name: <block>' sections. Each block runs until the next marker; trailing ';' removed."""
    blocks: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        m = re.match(r"^\s*--\s*name:\s*([A-Za-z_][A-Za-z0-9_]*)\s*$", line)
        if m:
            current = m.group(1)
            blocks[current] = []
        elif current is not None:
            blocks[current].append(line)
    result = {}
    for name, lines in blocks.items():
        body = "\n".join(lines).strip()
        while body.endswith(";"):
            body = body[:-1].rstrip()
        result[name] = body
    return result


def _normalise(v: Any) -> Any:
    """Make values look the same from both drivers: Decimal -> int/float, NaN -> None."""
    if isinstance(v, decimal.Decimal):
        if v == v.to_integral_value():
            return int(v)
        return float(v)
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


def _prepare_value(v: Any) -> Any:
    """Values passed to insert_rows: dicts/lists become JSON text."""
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return v


# --------------------------------------------------------------------------------------------
# Base
# --------------------------------------------------------------------------------------------

class Database:
    dialect: str = "?"

    def __init__(self) -> None:
        self._lock = threading.RLock()

    # -- public interface ---------------------------------------------------------------------
    def query(self, sql: str, params: Any = None) -> list[dict]:
        raise NotImplementedError

    def execute(self, sql: str, params: Any = None) -> None:
        raise NotImplementedError

    def insert_rows(self, table: str, rows: list[dict]) -> None:
        raise NotImplementedError

    def insert_df(self, table: str, df) -> None:
        raise NotImplementedError

    def run_script(self, path: str | os.PathLike) -> None:
        text = repo_path(path).read_text(encoding="utf-8")
        for stmt in split_statements(text):
            self.execute(stmt)

    def named_blocks(self, path: str | os.PathLike) -> dict[str, str]:
        return parse_named_blocks(repo_path(path).read_text(encoding="utf-8"))

    def table_exists(self, table: str) -> bool:
        schema, name = table.split(".")
        rows = self._table_exists_rows(schema, name)
        return bool(rows)

    def close(self) -> None:
        pass

    # -- helpers ------------------------------------------------------------------------------
    def _table_exists_rows(self, schema: str, name: str) -> list:
        raise NotImplementedError

    @staticmethod
    def _check_params(sql: str, params: Any) -> None:
        if params is not None and not isinstance(params, (dict, list, tuple)):
            raise TypeError("params must be a dict (for :name) or a list/tuple (for ?)")


# --------------------------------------------------------------------------------------------
# DuckDB
# --------------------------------------------------------------------------------------------

class DuckDatabase(Database):
    dialect = "duckdb"

    def __init__(self, path: Path) -> None:
        super().__init__()
        import duckdb

        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._con = duckdb.connect(str(path))

    @staticmethod
    def _rewrite(sql: str, params: Any) -> tuple[str, Any]:
        """`:name` -> `$name` (DuckDB named params); `::` casts are left alone.
        DuckDB rejects unused named params, so only the referenced ones are passed on."""
        if not isinstance(params, dict):
            return sql, params
        out, used = [], set()

        def sub(m: re.Match) -> str:
            used.add(m.group(1))
            return "$" + m.group(1)

        for kind, tok in _scan(sql):
            if kind == "code":
                tok = re.sub(r"(?<![:\w]):([A-Za-z_]\w*)", sub, tok)
            out.append(tok)
        missing = used - params.keys()
        if missing:
            raise KeyError(f"missing SQL parameter(s): {sorted(missing)}")
        return "".join(out), {k: v for k, v in params.items() if k in used}

    def _run(self, sql: str, params: Any):
        self._check_params(sql, params)
        sql, params = self._rewrite(sql, params)
        if not params:
            return self._con.execute(sql)
        return self._con.execute(sql, params)

    def query(self, sql: str, params: Any = None) -> list[dict]:
        with self._lock:
            cur = self._run(sql, params)
            if cur.description is None:
                return []
            cols = [d[0].lower() for d in cur.description]
            return [{c: _normalise(v) for c, v in zip(cols, row)} for row in cur.fetchall()]

    def execute(self, sql: str, params: Any = None) -> None:
        with self._lock:
            self._run(sql, params)

    def insert_rows(self, table: str, rows: list[dict]) -> None:
        if not rows:
            return
        cols = list(rows[0].keys())
        sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})"
        data = [[_prepare_value(r.get(c)) for c in cols] for r in rows]
        with self._lock:
            self._con.executemany(sql, data)

    def insert_df(self, table: str, df) -> None:
        if len(df) == 0:
            return
        cols = ", ".join(df.columns)
        with self._lock:
            self._con.register("_tl_insert_df", df)
            try:
                self._con.execute(f"INSERT INTO {table} ({cols}) SELECT {cols} FROM _tl_insert_df")
            finally:
                self._con.unregister("_tl_insert_df")

    def _table_exists_rows(self, schema: str, name: str) -> list:
        return self.query(
            "SELECT 1 AS x FROM information_schema.tables WHERE table_schema = ? AND table_name = ?",
            [schema.lower(), name.lower()],
        )

    def close(self) -> None:
        with self._lock:
            self._con.close()


# --------------------------------------------------------------------------------------------
# Exasol
# --------------------------------------------------------------------------------------------

def _exa_literal(v: Any) -> str:
    v = _prepare_value(v)
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, decimal.Decimal)):
        return str(v)
    if isinstance(v, float):
        if math.isnan(v):
            return "NULL"
        return repr(v)
    if isinstance(v, _dt.datetime):
        return "TIMESTAMP '" + v.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] + "'"
    if isinstance(v, _dt.date):
        return "DATE '" + v.isoformat() + "'"
    return "'" + str(v).replace("'", "''") + "'"


class ExaDatabase(Database):
    dialect = "exasol"

    def __init__(self, dsn: str, user: str, password: str) -> None:
        super().__init__()
        import pyexasol

        opts: dict[str, Any] = dict(
            dsn=dsn,
            user=user,
            password=password,
            fetch_dict=True,
            lower_ident=True,
            fetch_mapper=pyexasol.exasol_mapper,
            quote_ident=True,  # import_from_* gets uppercase names from us, quoted -> exact match
            encryption=True,
            compression=True,
        )
        # Exasol Personal uses a self-signed certificate. Preferred: put the certificate fingerprint
        # in the DSN (host/FINGERPRINT:8563). Otherwise EXASOL_SSL_VERIFY=false disables verification.
        if os.getenv("EXASOL_SSL_VERIFY", "true").lower() in ("0", "false", "no"):
            import ssl

            opts["websocket_sslopt"] = {"cert_reqs": ssl.CERT_NONE}
        self._con = pyexasol.connect(**opts)
        # Make DATE/TIMESTAMP -> VARCHAR casts identical to DuckDB's ISO output.
        self._con.execute("ALTER SESSION SET NLS_DATE_FORMAT = 'YYYY-MM-DD'")
        self._con.execute("ALTER SESSION SET NLS_TIMESTAMP_FORMAT = 'YYYY-MM-DD HH24:MI:SS.FF3'")

    @staticmethod
    def _rewrite(sql: str, params: Any) -> str:
        """Inline parameters as escaped literals and quote Exasol-reserved contract names."""
        positional = list(params) if isinstance(params, (list, tuple)) else None
        named = params if isinstance(params, dict) else None
        pos = 0
        out = []
        for kind, tok in _scan(sql):
            if kind != "code":
                out.append(tok)
                continue
            res, i = [], 0
            while i < len(tok):
                c = tok[i]
                if c == "?" and positional is not None:
                    if pos >= len(positional):
                        raise ValueError("not enough positional parameters")
                    res.append(_exa_literal(positional[pos]))
                    pos += 1
                    i += 1
                elif c == ":" and named is not None and i + 1 < len(tok) and (tok[i + 1].isalpha() or tok[i + 1] == "_") \
                        and (i == 0 or tok[i - 1] != ":"):
                    m = _NAME_RE.match(tok, i + 1)
                    name = m.group(0)
                    if name not in named:
                        raise KeyError(f"missing SQL parameter :{name}")
                    res.append(_exa_literal(named[name]))
                    i = m.end()
                elif c.isalpha() or c == "_":
                    m = _NAME_RE.match(tok, i)
                    word = m.group(0)
                    prev = tok[i - 1] if i > 0 else ""
                    if word.lower() in EXASOL_QUOTED and not (prev.isalnum() or prev == "_"):
                        res.append('"' + word.upper() + '"')
                    else:
                        res.append(word)
                    i = m.end()
                else:
                    res.append(c)
                    i += 1
            out.append("".join(res))
        if positional is not None and pos != len(positional):
            raise ValueError("too many positional parameters")
        return "".join(out)

    def query(self, sql: str, params: Any = None) -> list[dict]:
        self._check_params(sql, params)
        with self._lock:
            stmt = self._con.execute(self._rewrite(sql, params))
            if stmt.result_type != "resultSet":
                return []
            return [{k.lower(): _normalise(v) for k, v in row.items()} for row in stmt.fetchall()]

    def execute(self, sql: str, params: Any = None) -> None:
        self._check_params(sql, params)
        with self._lock:
            self._con.execute(self._rewrite(sql, params))

    def insert_rows(self, table: str, rows: list[dict], batch: int = 500) -> None:
        if not rows:
            return
        cols = list(rows[0].keys())
        head = f"INSERT INTO {table} ({', '.join(cols)}) VALUES "
        for k in range(0, len(rows), batch):
            values = ", ".join(
                "(" + ", ".join(_exa_literal(r.get(c)) for c in cols) + ")" for r in rows[k : k + batch]
            )
            self.execute(head + values)

    def insert_df(self, table: str, df) -> None:
        if len(df) == 0:
            return
        import pandas as pd

        out = df.copy()
        for col in out.columns:
            s = out[col]
            if pd.api.types.is_datetime64_any_dtype(s):
                out[col] = s.dt.strftime("%Y-%m-%d %H:%M:%S").where(s.notna(), None)
            elif s.dtype == object:
                out[col] = s.map(
                    lambda v: v.isoformat() if isinstance(v, (_dt.date, _dt.datetime))
                    else ("TRUE" if v is True else "FALSE" if v is False else v)
                )
        schema, name = table.split(".")
        with self._lock:
            self._con.import_from_pandas(
                out,
                (schema.upper(), name.upper()),
                import_params={"columns": [c.upper() for c in out.columns], "null": ""},
            )

    def _table_exists_rows(self, schema: str, name: str) -> list:
        return self.query(
            "SELECT 1 AS x FROM exa_all_tables WHERE table_schema = ? AND table_name = ?",
            [schema.upper(), name.upper()],
        )

    def close(self) -> None:
        with self._lock:
            self._con.close()


# --------------------------------------------------------------------------------------------
# Factory
# --------------------------------------------------------------------------------------------

_db: Database | None = None
_db_lock = threading.Lock()


def get_db() -> Database:
    """Exasol if EXASOL_DSN is set, else DuckDB at DUCKDB_PATH (default data/trustlens.duckdb)."""
    global _db
    with _db_lock:
        if _db is None:
            dsn = os.getenv("EXASOL_DSN", "").strip()
            if dsn:
                _db = ExaDatabase(dsn, os.getenv("EXASOL_USER", "sys"), os.getenv("EXASOL_PASSWORD", ""))
            else:
                _db = DuckDatabase(repo_path(os.getenv("DUCKDB_PATH", "data/trustlens.duckdb")))
        return _db


def reset_db() -> None:
    """Close and forget the cached connection (tests, CLI tools)."""
    global _db
    with _db_lock:
        if _db is not None:
            _db.close()
        _db = None


def _main(argv: Iterable[str]) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="python -m app.db")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="connect and print dialect + server time")
    run = sub.add_parser("run", help="run a .sql script")
    run.add_argument("path")
    args = ap.parse_args(list(argv))

    db = get_db()
    if args.cmd == "check":
        now = db.query("SELECT CURRENT_TIMESTAMP AS now_ts")[0]["now_ts"]
        print(f"dialect={db.dialect} now={now}")
        if db.table_exists("curated.patients"):
            print("patients:", db.query("SELECT COUNT(*) AS n FROM curated.patients")[0]["n"])
    elif args.cmd == "run":
        db.run_script(args.path)
        print(f"ran {args.path} on {db.dialect}")
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(_main(sys.argv[1:]))


# --------------------------------------------------------------------------------------------
# Compatibility with the M0 interface (Dev B code and tests)
# --------------------------------------------------------------------------------------------

DB = Database


def DuckDB(path: str | os.PathLike) -> DuckDatabase:
    """DuckDB at a path, or ':memory:' (tests)."""
    return DuckDatabase(Path(path) if str(path) == ":memory:" else repo_path(path))


def set_db(db: Database | None) -> None:
    """Swap the cached connection (tests use an in-memory DuckDB). Does not close the old one."""
    global _db
    with _db_lock:
        _db = db


def table_count(db: Database, table: str) -> int | None:
    try:
        return int(db.query(f"SELECT COUNT(*) AS n FROM {table}")[0]["n"])
    except Exception:
        return None
