"""Summary pipeline: facts -> generator -> (inject_error) -> critic -> verifier -> route -> persist, lineage, audit."""
from __future__ import annotations

import json
import uuid

from .. import audit, lineage
from ..audit import now_iso
from ..db import DB, get_db
from . import agents, critic, facts as facts_mod, templates

PATIENT_PLACEHOLDER = "Part of this summary is waiting for your care team to check it."


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def get_summary(patient_id: str, audience: str, inject_error: bool = False, refresh: bool = False,
                db: DB | None = None) -> dict:
    db = db or get_db()
    if not inject_error and not refresh:
        cached = db.query(
            "SELECT summary_id FROM clinical.summaries WHERE patient_id = ? AND audience = ? AND inject_error = FALSE "
            "ORDER BY created_at DESC LIMIT 1", [patient_id, audience])
        if cached:
            return load_summary(cached[0]["summary_id"], db)
    return generate_summary(patient_id, audience, inject_error, db)


def evaluate(patient_id: str, audience: str, inject_error: bool, db: DB) -> dict:
    """Run generator -> critic -> verifier without persisting anything (used by the evals).

    Returns {"sentences": [{"text", "critic", "verifier", "ok"}], "injected": ..., "model": ...}."""
    selected = templates.facts_for(audience, facts_mod.compute(patient_id, db))
    facts_by_id = {f["fact_id"]: f for f in selected}
    gen = agents.generate(audience, selected)
    out = gen.parsed if gen.ok else agents._stub_generate(audience, selected)
    injected = agents.inject_error(out, facts_by_id) if inject_error else None
    flat = [s for section in out.sections for s in section.sentences]
    critic_results = [critic.check(s.text, s.fact_ids, facts_by_id, audience) for s in flat]
    verdicts, _ = agents.verify([{"index": i, "text": s.text, "facts": [facts_by_id[f]["data"] for f in s.fact_ids
                                                                         if f in facts_by_id]}
                                 for i, s in enumerate(flat)], critic_results)
    return {"model": gen.meta["model"] if gen.ok else "template-fallback", "injected": injected, "sentences": [
        {"text": s.text, "critic": c, "verifier": v, "ok": c["status"] == "PASS" and v["status"] == "SUPPORTED"}
        for s, c, v in zip(flat, critic_results, verdicts)]}


def generate_summary(patient_id: str, audience: str, inject_error: bool, db: DB) -> dict:
    all_facts = facts_mod.compute(patient_id, db)  # raises PatientNotFound
    selected = templates.facts_for(audience, all_facts)
    facts_by_id = {f["fact_id"]: f for f in selected}

    gen = agents.generate(audience, selected)
    model, prompt_hash = gen.meta["model"], gen.meta["prompt_hash"]
    generator_note = None
    if gen.ok:
        out = gen.parsed
    else:  # LLM down or refused: fall back to deterministic templates, and say so in the audit log
        out = agents._stub_generate(audience, selected)
        model, generator_note = "template-fallback", gen.meta.get("error")

    injected = agents.inject_error(out, facts_by_id) if inject_error else None

    flat = [(s_i, section.title, sentence) for s_i, section in enumerate(out.sections) for sentence in section.sentences]
    critic_results = [critic.check(s.text, s.fact_ids, facts_by_id, audience) for _, _, s in flat]
    verify_items = [{"index": i, "text": s.text, "facts": [facts_by_id[f]["data"] for f in s.fact_ids if f in facts_by_id]}
                    for i, (_, _, s) in enumerate(flat)]
    verdicts, verifier_meta = agents.verify(verify_items, critic_results)

    summary_id = _new_id("SUM")
    now = now_iso()
    sentence_rows, flagged = [], []
    for i, ((_, title, s), c, v) in enumerate(zip(flat, critic_results, verdicts)):
        ok = c["status"] == "PASS" and v["status"] == "SUPPORTED"
        row = {
            "sentence_id": _new_id("SEN"), "summary_id": summary_id, "sort_order": i, "section": title,
            "sentence_text": s.text, "fact_ids": ",".join(s.fact_ids), "critic_status": c["status"],
            "critic_reasons": json.dumps(c["reasons"]), "verifier_status": v["status"], "verifier_reason": v["reason"],
            "review_status": "auto_ok" if ok else "needs_review", "reviewed_by": None, "reviewed_at": None,
        }
        sentence_rows.append(row)
        if not ok:
            flagged.append(row)

    overall = "needs_review" if flagged else "verified"
    db.insert_rows("clinical.summaries", [{
        "summary_id": summary_id, "patient_id": patient_id, "audience": audience, "inject_error": inject_error,
        "overall_status": overall, "model": model, "prompt_hash": prompt_hash, "created_at": now}])
    db.insert_rows("clinical.sentences", sentence_rows)

    for row in sentence_rows:
        cited = [f for f in row["fact_ids"].split(",") if f in facts_by_id]
        lineage.add(row["sentence_id"], "sentence", [(f, "fact") for f in cited], transform="summary.generate",
                    agent="generator", model=model, prompt_hash=prompt_hash, db=db)
        if verifier_meta.get("call_id"):
            lineage.add(row["sentence_id"], "sentence", [(verifier_meta["call_id"], "llm_call")],
                        transform="summary.verify", agent="verifier", model=verifier_meta.get("model"),
                        prompt_hash=verifier_meta.get("prompt_hash"), db=db)
    lineage.add(summary_id, "summary", [(r["sentence_id"], "sentence") for r in sentence_rows],
                transform="summary.assemble", db=db)

    seq = audit.append("system:summary", "summary.generated", summary_id, {
        "patient_id": patient_id, "audience": audience, "sentences": len(sentence_rows), "flagged": len(flagged),
        "inject_error": injected, "model": model, "prompt_hash": prompt_hash, "generator_error": generator_note,
    }, db=db)
    for row in flagged:
        seq = audit.append("system:critic", "sentence.flagged", row["sentence_id"], {
            "summary_id": summary_id, "critic": row["critic_status"], "reasons": json.loads(row["critic_reasons"]),
            "verifier": row["verifier_status"], "verifier_reason": row["verifier_reason"]}, db=db)
    return load_summary(summary_id, db, audit_seq=seq)


def load_summary(summary_id: str, db: DB, audit_seq: int | None = None) -> dict:
    s = db.query("SELECT summary_id, patient_id, audience, model, prompt_hash FROM clinical.summaries "
                 "WHERE summary_id = ?", [summary_id])[0]
    rows = db.query("SELECT * FROM clinical.sentences WHERE summary_id = ? ORDER BY sort_order", [summary_id])
    fact_rows = db.query("SELECT fact_id, kind, data_json, source_row_ids FROM clinical.facts WHERE patient_id = ?",
                         [s["patient_id"]])
    facts = [{"fact_id": f["fact_id"], "kind": f["kind"], "data": json.loads(f["data_json"]),
              "source_row_ids": [x for x in f["source_row_ids"].split(",") if x]} for f in fact_rows]
    facts = templates.facts_for(s["audience"], facts)

    sections: dict[str, list[dict]] = {}
    needs_review = False
    for r in rows:
        if r["review_status"] == "rejected":
            continue
        pending = r["review_status"] == "needs_review"
        needs_review = needs_review or pending
        if pending and s["audience"] == "patient":
            status, text = "hidden_pending_review", PATIENT_PLACEHOLDER
        else:
            status, text = ("needs_review" if pending else "verified"), r["sentence_text"]
        sections.setdefault(r["section"], []).append({
            "sentence_id": r["sentence_id"], "text": text, "fact_ids": [f for f in r["fact_ids"].split(",") if f],
            "status": status,
            "critic": {"status": r["critic_status"], "reasons": json.loads(r["critic_reasons"] or "[]")},
            "verifier": {"status": r["verifier_status"], "reason": r["verifier_reason"] or ""},
        })
    order = templates.SECTION_ORDER[s["audience"]]
    titles = sorted(sections, key=lambda t: order.index(t) if t in order else len(order))
    if audit_seq is None:
        last = db.query("SELECT seq FROM gov.audit_events WHERE subject = ? ORDER BY seq DESC LIMIT 1", [summary_id])
        audit_seq = int(last[0]["seq"]) if last else 0
    return {
        "summary_id": summary_id, "patient_id": s["patient_id"], "audience": s["audience"],
        "overall_status": "needs_review" if needs_review else "verified",
        "sections": [{"title": t, "sentences": sections[t]} for t in titles],
        "facts": facts, "model": s["model"], "prompt_hash": s["prompt_hash"], "audit_seq": audit_seq,
    }
