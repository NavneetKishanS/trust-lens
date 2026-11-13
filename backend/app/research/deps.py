"""Bridge from the research engine to the shared libs owned by other devs.

- `app.db`      (Dev A): get_db() -> object with query / execute / insert_rows / run_script / named_blocks / dialect
- `app.audit`   (Dev B): append(actor, action_type, subject, payload) -> seq
- `app.lineage` (Dev B): add(derived_id, derived_type, sources, transform, agent, model, prompt_hash), chain(id, max_depth)
- `app.llm`     (Dev B): call(purpose, prompt_file, variables, output_model) -> (parsed | None, meta)

When those modules exist we use them. Until they are merged, the fallbacks below follow the same contracts
(shared §6, §9; Dev A §6; Dev B §4) so the research engine runs and can be tested on its own.
Once A and B have merged, the fallbacks are dead code and can be deleted.

Research code must call these functions at runtime (`deps.get_db()`), never bind them at import time,
so tests can swap the database.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"

# --------------------------------------------------------------------------------------------- db


class FallbackDuckDB:
    """Minimal DuckDB implementation of Dev A's db.py interface."""

    dialect = "duckdb"

    def __init__(self, path: str | Path):
        import duckdb

        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(self.path)
        self._lock = threading.RLock()
        self._active = None

    @staticmethod
    def _adapt(sql: str, params: Any) -> tuple[str, Any]:
        # Named ':name' params (as used in facts.sql blocks) -> DuckDB '$name'. Leaves '::' casts alone.
        if isinstance(params, dict):
            def repl(m: re.Match) -> str:
                return f"${m.group(1)}" if m.group(1) in params else m.group(0)

            sql = re.sub(r"(?<![:\w]):([A-Za-z_]\w*)", repl, sql)
        return sql, params

    def query(self, sql: str, params: Any = None) -> list[dict]:
        sql, params = self._adapt(sql, params)
        with self._lock:
            cur = self._conn.cursor()
            self._active = cur
            try:
                cur.execute(sql, params) if params is not None else cur.execute(sql)
                cols = [d[0] for d in cur.description] if cur.description else []
                return [dict(zip(cols, r)) for r in cur.fetchall()]
            finally:
                self._active = None
                cur.close()

    def execute(self, sql: str, params: Any = None) -> None:
        sql, params = self._adapt(sql, params)
        with self._lock:
            self._conn.execute(sql, params) if params is not None else self._conn.execute(sql)

    def insert_rows(self, table: str, rows: list[dict]) -> None:
        if not rows:
            return
        cols = list(rows[0].keys())
        sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})"
        with self._lock:
            self._conn.executemany(sql, [[r.get(c) for c in cols] for r in rows])

    def run_script(self, path: str | Path) -> None:
        with self._lock:
            self._conn.execute(Path(path).read_text())

    @staticmethod
    def named_blocks(path: str | Path) -> dict[str, str]:
        return parse_named_blocks(Path(path).read_text())

    def interrupt(self) -> None:
        try:
            self._conn.interrupt()
        except Exception:  # noqa: BLE001 - best effort
            pass


def parse_named_blocks(text: str) -> dict[str, str]:
    """Parse '-- name: x' blocks (same format as db/facts.sql)."""
    blocks: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        m = re.match(r"\s*--\s*name:\s*(\w+)", line)
        if m:
            current = m.group(1)
            blocks[current] = []
        elif current:
            blocks[current].append(line)
    return {k: "\n".join(v).strip().rstrip(";") for k, v in blocks.items()}


_db_singleton = None
_db_lock = threading.Lock()


def get_db():
    global _db_singleton
    try:
        from app.db import get_db as real_get_db  # type: ignore

        return real_get_db()
    except ImportError:
        pass
    with _db_lock:
        if _db_singleton is None:
            path = os.environ.get("TRUSTLENS_DUCKDB") or str(REPO_ROOT / "data" / "trustlens.duckdb")
            _db_singleton = FallbackDuckDB(path)
            _ensure_gov_tables(_db_singleton)
        return _db_singleton


def use_db(db) -> None:
    """Point the fallback at a specific database (tests, dev scripts)."""
    global _db_singleton
    _db_singleton = db
    _ensure_gov_tables(db)


def table_exists(db, table: str) -> bool:
    try:
        db.query(f"SELECT 1 AS x FROM {table} WHERE 1 = 0")
        return True
    except Exception:  # noqa: BLE001 - any error means "not usable"
        return False


_GOV_DDL = """
CREATE SCHEMA IF NOT EXISTS gov;
CREATE TABLE IF NOT EXISTS gov.audit_events (seq INTEGER, event_ts VARCHAR(40), actor VARCHAR(200),
  action_type VARCHAR(60), subject VARCHAR(200), payload_json VARCHAR(2000000), prev_hash VARCHAR(64), row_hash VARCHAR(64));
CREATE TABLE IF NOT EXISTS gov.lineage_edges (derived_id VARCHAR(200), derived_type VARCHAR(60), source_id VARCHAR(200),
  source_type VARCHAR(60), transform VARCHAR(200), agent VARCHAR(60), model VARCHAR(100), prompt_hash VARCHAR(64), created_at TIMESTAMP);
CREATE TABLE IF NOT EXISTS gov.llm_calls (call_id VARCHAR(60), purpose VARCHAR(60), model VARCHAR(100), prompt_hash VARCHAR(64),
  input_hash VARCHAR(64), stop_reason VARCHAR(40), latency_ms INTEGER, ok BOOLEAN, created_at TIMESTAMP);
"""


def _ensure_gov_tables(db) -> None:
    # Only for the fallback DB; Dev A's schema.sql creates these in the real one.
    if isinstance(db, FallbackDuckDB):
        db.execute(_GOV_DDL)


# ------------------------------------------------------------------------------------------ audit

_audit_lock = threading.Lock()
GENESIS = "0" * 64


def _row_hash(prev_hash: str, event_ts: str, actor: str, action_type: str, subject: str, payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    raw = "|".join([prev_hash, event_ts, actor, action_type, subject, canonical])
    return hashlib.sha256(raw.encode()).hexdigest()


def audit_append(actor: str, action_type: str, subject: str, payload: dict) -> int:
    try:
        from app.audit import append  # type: ignore

        return append(actor, action_type, subject, payload)
    except ImportError:
        pass
    db = get_db()
    with _audit_lock:
        last = db.query("SELECT seq, row_hash FROM gov.audit_events ORDER BY seq DESC LIMIT 1")
        seq = (last[0]["seq"] + 1) if last else 1
        prev = last[0]["row_hash"] if last else GENESIS
        ts = datetime.now(timezone.utc).isoformat()
        payload = json.loads(json.dumps(payload, default=str))
        db.insert_rows("gov.audit_events", [dict(
            seq=seq, event_ts=ts, actor=actor, action_type=action_type, subject=subject,
            payload_json=json.dumps(payload, sort_keys=True, separators=(",", ":")), prev_hash=prev,
            row_hash=_row_hash(prev, ts, actor, action_type, subject, payload))])
        return seq


def audit_verify() -> dict:
    try:
        from app.audit import verify  # type: ignore

        return verify()
    except ImportError:
        pass
    prev, n = GENESIS, 0
    for r in get_db().query("SELECT * FROM gov.audit_events ORDER BY seq"):
        n += 1
        payload = json.loads(r["payload_json"] or "{}")
        if r["prev_hash"] != prev or r["row_hash"] != _row_hash(prev, r["event_ts"], r["actor"], r["action_type"],
                                                                r["subject"], payload):
            return dict(valid=False, length=n, broken_at=r["seq"])
        prev = r["row_hash"]
    return dict(valid=True, length=n, broken_at=None)


# ---------------------------------------------------------------------------------------- lineage


def lineage_add(derived_id: str, derived_type: str, sources: list[tuple[str, str]], transform: str,
                agent: str | None = None, model: str | None = None, prompt_hash: str | None = None) -> None:
    try:
        from app.lineage import add  # type: ignore

        return add(derived_id, derived_type, sources, transform, agent=agent, model=model, prompt_hash=prompt_hash)
    except ImportError:
        pass
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    get_db().insert_rows("gov.lineage_edges", [dict(
        derived_id=derived_id, derived_type=derived_type, source_id=sid, source_type=stype, transform=transform,
        agent=agent, model=model, prompt_hash=prompt_hash, created_at=now) for sid, stype in sources])


def lineage_chain(item_id: str, max_depth: int = 4) -> list[dict]:
    try:
        from app.lineage import chain  # type: ignore

        return chain(item_id, max_depth=max_depth)
    except ImportError:
        pass
    db = get_db()
    out, frontier, seen = [], [item_id], {item_id}
    for depth in range(1, max_depth + 1):
        nxt = []
        for did in frontier:
            for r in db.query("SELECT * FROM gov.lineage_edges WHERE derived_id = ?", [did]):
                out.append(dict(id=r["source_id"], type=r["source_type"], transform=r["transform"], agent=r["agent"],
                                model=r["model"], prompt_hash=r["prompt_hash"], depth=depth, derived_from=did))
                if r["source_id"] not in seen:
                    seen.add(r["source_id"])
                    nxt.append(r["source_id"])
        frontier = nxt
    return out


# -------------------------------------------------------------------------------------------- llm


def llm_provider() -> str:
    return (os.environ.get("LLM_PROVIDER") or "stub").strip().lower()


def prompt_hash(prompt_file: str) -> str:
    return hashlib.sha256((PROMPTS_DIR / prompt_file).read_bytes()).hexdigest()


def render_prompt(prompt_file: str, variables: dict) -> str:
    text = (PROMPTS_DIR / prompt_file).read_text()
    for k, v in variables.items():
        text = text.replace("{{" + k + "}}", v if isinstance(v, str) else json.dumps(v, ensure_ascii=False))
    return text


def llm_call(purpose: str, prompt_file: str, variables: dict, output_model, effort: str = "low"):
    """Returns (parsed | None, meta). Never raises; failures come back as (None, meta with ok=False)."""
    try:
        from app.llm import call as real_call  # type: ignore

        if "effort" in inspect.signature(real_call).parameters:
            return real_call(purpose, prompt_file, variables, output_model, effort=effort)
        return real_call(purpose, prompt_file, variables, output_model)
    except ImportError:
        pass
    return _fallback_llm_call(purpose, prompt_file, variables, output_model, effort)


def _fallback_llm_call(purpose, prompt_file, variables, output_model, effort):
    provider = llm_provider()
    text = render_prompt(prompt_file, variables)
    meta = dict(model="stub", prompt_hash=prompt_hash(prompt_file),
                input_hash=hashlib.sha256(text.encode()).hexdigest(), stop_reason=None, latency_ms=0, ok=False)
    if provider == "stub":
        meta["stop_reason"] = "stub"
        return None, meta
    t0 = time.time()
    parsed = None
    try:
        import anthropic

        if provider == "bedrock":
            client = anthropic.AnthropicBedrockMantle(aws_region=os.environ.get("AWS_REGION", "eu-central-1"))
            model = "anthropic.claude-opus-5-5"
        else:
            client = anthropic.Anthropic()
            model = "claude-opus-5-5"
        meta["model"] = model
        resp = client.messages.parse(model=model, max_tokens=16000, messages=[{"role": "user", "content": text}],
                                     output_format=output_model, output_config={"effort": effort})
        meta["stop_reason"] = resp.stop_reason
        if resp.stop_reason != "refusal" and resp.parsed_output is not None:
            parsed = resp.parsed_output
            meta["ok"] = True
    except Exception as e:  # noqa: BLE001 - callers handle ok=False
        meta["stop_reason"] = f"error:{type(e).__name__}"
    meta["latency_ms"] = int((time.time() - t0) * 1000)
    try:
        get_db().insert_rows("gov.llm_calls", [dict(
            call_id=f"LLM-{meta['input_hash'][:12]}-{int(t0 * 1000)}", purpose=purpose, model=meta["model"],
            prompt_hash=meta["prompt_hash"], input_hash=meta["input_hash"], stop_reason=meta["stop_reason"],
            latency_ms=meta["latency_ms"], ok=meta["ok"], created_at=datetime.now(timezone.utc).replace(tzinfo=None))])
    except Exception:  # noqa: BLE001 - logging must not break the call
        pass
    return parsed, meta
