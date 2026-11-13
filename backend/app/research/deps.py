"""Adapters from the research engine to the shared libs (Dev A: app.db; Dev B: app.audit, app.lineage, app.llm).

Research code calls these at runtime (`deps.get_db()`), never binds them at import time, so tests can swap the DB
with `app.db.set_db(...)`.
"""
from __future__ import annotations

import re
from typing import Any

from app import audit, config, lineage, llm
from app import db as dbmod
from app.schema import table_exists as _table_exists

REPO_ROOT = config.REPO_ROOT
PROMPTS_DIR = config.PROMPTS_DIR


# ------------------------------------------------------------------------------------------- db


def get_db():
    return dbmod.get_db()


def table_exists(db, table: str) -> bool:
    return _table_exists(db, table)


def parse_named_blocks(text: str) -> dict[str, str]:
    """Parse '-- name: x' blocks (same format as db/facts.sql) from text."""
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


_NAMED = re.compile(r"(?<![:\w]):([A-Za-z_]\w*)")


def bind_named(sql: str, params: dict[str, Any]) -> tuple[str, list]:
    """':name' placeholders → '?' + positional list (app.db only supports '?'). Leaves '::' casts and strings alone."""
    values: list = []
    out, pos = [], 0
    for m in re.finditer(r"'(?:[^']|'')*'", sql):  # skip string literals
        out.append(_bind_part(sql[pos:m.start()], params, values))
        out.append(m.group(0))
        pos = m.end()
    out.append(_bind_part(sql[pos:], params, values))
    return "".join(out), values


def _bind_part(part: str, params: dict, values: list) -> str:
    def repl(m: re.Match) -> str:
        if m.group(1) not in params:
            return m.group(0)
        values.append(params[m.group(1)])
        return "?"

    return _NAMED.sub(repl, part)


def query_named(db, sql: str, params: dict[str, Any]) -> list[dict]:
    q, values = bind_named(sql, params)
    return db.query(q, values)


# ---------------------------------------------------------------------------------- audit + lineage


def audit_append(actor: str, action_type: str, subject: str, payload: dict) -> int:
    return audit.append(actor, action_type, subject, payload)


def audit_verify() -> dict:
    return audit.verify()


def lineage_add(derived_id: str, derived_type: str, sources: list[tuple[str, str]], transform: str | None,
                agent: str | None = None, model: str | None = None, prompt_hash: str | None = None) -> None:
    lineage.add(derived_id, derived_type, sources, transform, agent=agent, model=model, prompt_hash=prompt_hash)


def lineage_chain(item_id: str, max_depth: int = 4) -> list[dict]:
    return lineage.chain(item_id, max_depth=max_depth)["chain"]


# ------------------------------------------------------------------------------------------- llm


def llm_provider() -> str:
    return llm.provider()


def prompt_hash(prompt_file: str) -> str:
    return llm.load_prompt(prompt_file)[1]


def llm_call(purpose: str, prompt_file: str, variables: dict, output_model, effort: str = "low"):
    """Returns (parsed | None, meta). Research code handles stub mode itself (templates / keyword stub) and only
    calls this for a real provider, so the stub callback is never the source of an answer."""
    result = llm.call(purpose, prompt_file, variables, output_model, stub=lambda: None, effort=effort)
    return (result.parsed if result.ok else None), result.meta
