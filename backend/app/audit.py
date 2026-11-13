"""Hash-chained audit log (shared §9).

row_hash = sha256(prev_hash|event_ts|actor|action_type|subject|payload_canonical), genesis prev_hash = "0"*64.
"""
from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from typing import Any

from .db import DB, get_db

GENESIS = "0" * 64
ACTION_TYPES = {
    "data.loaded", "summary.generated", "sentence.flagged", "report.submitted", "symptom.flagged",
    "review.decision", "ask.answered", "ask.blocked", "kg.built", "edge.accepted", "edge.rejected",
    "eval.completed",
}
_lock = threading.Lock()


def canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def compute_hash(prev_hash: str, event_ts: str, actor: str, action_type: str, subject: str, payload_json: str) -> str:
    raw = "|".join([prev_hash, event_ts, actor, action_type, subject, payload_json])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def append(actor: str, action_type: str, subject: str, payload: dict | None = None, db: DB | None = None) -> int:
    """Append one event and return its seq."""
    if action_type not in ACTION_TYPES:
        raise ValueError(f"unknown action_type {action_type!r}; add it to shared §9 first")
    db = db or get_db()
    payload_json = canonical(payload or {})
    with _lock:
        last = db.query("SELECT seq, row_hash FROM gov.audit_events ORDER BY seq DESC LIMIT 1")
        seq = int(last[0]["seq"]) + 1 if last else 1
        prev_hash = last[0]["row_hash"] if last else GENESIS
        event_ts = now_iso()
        row_hash = compute_hash(prev_hash, event_ts, actor, action_type, subject, payload_json)
        db.execute(
            "INSERT INTO gov.audit_events (seq, event_ts, actor, action_type, subject, payload_json, prev_hash, row_hash)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [seq, event_ts, actor, action_type, subject, payload_json, prev_hash, row_hash],
        )
    return seq


def list_events(limit: int = 100, db: DB | None = None) -> list[dict]:
    db = db or get_db()
    rows = db.query(
        "SELECT seq, event_ts, actor, action_type, subject, payload_json, prev_hash, row_hash"
        f" FROM gov.audit_events ORDER BY seq DESC LIMIT {int(limit)}"
    )
    return [
        {**{k: v for k, v in r.items() if k != "payload_json"}, "seq": int(r["seq"]),
         "payload": json.loads(r["payload_json"] or "{}")}
        for r in rows
    ]


def verify(db: DB | None = None) -> dict:
    """Recompute every row in order. Broken = wrong hash, wrong link, or a gap in seq."""
    db = db or get_db()
    rows = db.query(
        "SELECT seq, event_ts, actor, action_type, subject, payload_json, prev_hash, row_hash"
        " FROM gov.audit_events ORDER BY seq"
    )
    prev = GENESIS
    for expected_seq, r in enumerate(rows, start=1):
        seq = int(r["seq"])
        recomputed = compute_hash(r["prev_hash"], r["event_ts"], r["actor"], r["action_type"], r["subject"],
                                  r["payload_json"] or canonical({}))
        if seq != expected_seq or r["prev_hash"] != prev or recomputed != r["row_hash"]:
            return {"valid": False, "length": len(rows), "broken_at": seq}
        prev = r["row_hash"]
    return {"valid": True, "length": len(rows), "broken_at": None}
