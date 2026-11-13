"""Lineage edges: derived artefact -> sources, with transform, agent, model and prompt hash."""
from __future__ import annotations

from .audit import now_iso
from .db import DB, get_db


def add(
    derived_id: str,
    derived_type: str,
    sources: list[tuple[str, str]],
    transform: str | None = None,
    agent: str | None = None,
    model: str | None = None,
    prompt_hash: str | None = None,
    db: DB | None = None,
) -> None:
    db = db or get_db()
    created_at = now_iso()
    db.insert_rows("gov.lineage_edges", [
        {"derived_id": derived_id, "derived_type": derived_type, "source_id": sid, "source_type": stype,
         "transform": transform, "agent": agent, "model": model, "prompt_hash": prompt_hash, "created_at": created_at}
        for sid, stype in sources
    ])


def chain(item_id: str, max_depth: int = 4, db: DB | None = None) -> dict:
    """Walk upstream breadth-first. Returns the shared §7 /lineage shape, or type=None if unknown."""
    db = db or get_db()
    sql = ("SELECT derived_id, derived_type, source_id, source_type, transform, agent, model, prompt_hash"
           " FROM gov.lineage_edges WHERE derived_id = ?")
    first = db.query(sql, [item_id])
    if not first:
        return {"id": item_id, "type": None, "chain": [], "producer": None}

    producer = next(({"agent": e["agent"], "model": e["model"], "prompt_hash": e["prompt_hash"]}
                     for e in first if e["agent"]), None)
    out, seen, frontier = [], {item_id}, [(item_id, 0)]
    while frontier:
        current, depth = frontier.pop(0)
        if depth >= max_depth:
            continue
        for e in (first if current == item_id else db.query(sql, [current])):
            if e["source_id"] in seen:
                continue
            seen.add(e["source_id"])
            out.append({"id": e["source_id"], "type": e["source_type"], "transform": e["transform"],
                        "agent": e["agent"], "model": e["model"], "prompt_hash": e["prompt_hash"], "depth": depth + 1})
            frontier.append((e["source_id"], depth + 1))
    return {"id": item_id, "type": first[0]["derived_type"], "chain": out, "producer": producer}
