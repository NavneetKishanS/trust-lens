"""Clinician review queue: flagged summary sentences + pending patient symptoms. Every decision is audited."""
from __future__ import annotations

import json

from .. import audit
from ..audit import now_iso
from ..db import DB, get_db


class ItemNotFound(Exception):
    pass


class AlreadyDecided(Exception):
    pass


def queue(db: DB | None = None) -> list[dict]:
    db = db or get_db()
    items = []
    for r in db.query(
            "SELECT s.sentence_id, s.sentence_text, s.fact_ids, s.critic_status, s.critic_reasons, s.verifier_status, "
            "s.verifier_reason, m.patient_id, m.audience, m.created_at FROM clinical.sentences s "
            "JOIN clinical.summaries m ON m.summary_id = s.summary_id WHERE s.review_status = 'needs_review'"):
        reasons = json.loads(r["critic_reasons"] or "[]")
        why = [f"critic: {'; '.join(reasons)}"] if reasons else []
        if r["verifier_status"] != "SUPPORTED":
            why.append(f"verifier {r['verifier_status']}: {r['verifier_reason']}")
        items.append({"item_id": r["sentence_id"], "kind": "sentence", "patient_id": r["patient_id"],
                      "text": r["sentence_text"], "reason": f"{r['audience']} summary — " + " | ".join(why),
                      "evidence": [{"kind": "fact", "id": f} for f in r["fact_ids"].split(",") if f],
                      "created_at": r["created_at"]})
    for r in db.query(
            "SELECT symptom_id, patient_id, span, term, classification, reason, evidence_json, exposure_label, created_at "
            "FROM community.symptoms WHERE review_status = 'pending'"):
        items.append({"item_id": r["symptom_id"], "kind": "symptom", "patient_id": r["patient_id"],
                      "text": f"{r['term']} (patient wrote: \"{r['span']}\")",
                      "reason": f"{r['classification']}: {r['reason']}",
                      "evidence": json.loads(r["evidence_json"] or "[]"), "created_at": r["created_at"]})
    return sorted(items, key=lambda i: i["created_at"], reverse=True)


def decide(item_id: str, decision: str, reviewer: str, note: str = "", db: DB | None = None) -> int:
    db = db or get_db()
    if item_id.startswith("SEN-"):
        table, key, pending, kind = "clinical.sentences", "sentence_id", "needs_review", "sentence"
        note_col = ""
    elif item_id.startswith("SYM-"):
        table, key, pending, kind = "community.symptoms", "symptom_id", "pending", "symptom"
        note_col = ", review_note = ?"
    else:
        raise ItemNotFound(item_id)
    rows = db.query(f"SELECT review_status FROM {table} WHERE {key} = ?", [item_id])
    if not rows:
        raise ItemNotFound(item_id)
    if rows[0]["review_status"] != pending:
        raise AlreadyDecided(f"{item_id} is already {rows[0]['review_status']}")
    status = "approved" if decision == "approve" else "rejected"
    params = [status, reviewer, now_iso()] + ([note] if note_col else []) + [item_id]
    db.execute(f"UPDATE {table} SET review_status = ?, reviewed_by = ?, reviewed_at = ?{note_col} WHERE {key} = ?", params)
    return audit.append(f"clinician:{reviewer}", "review.decision", item_id,
                        {"kind": kind, "decision": decision, "status": status, "note": note})
