"""Symptom intake: extract (LLM, spans verified) -> map to vocabulary -> classify (rules, shared §8) -> store -> queue.

EXPECTED   listed side effect of a vaccine/medicine the patient received, onset within the window   -> stats only
IN_RECORD  already documented in the patient's record (condition in the last 365 days)            -> stats only
NEW        mapped to the vocabulary but neither of the above                                      -> clinician review
UNMAPPED   couldn't be mapped to the vocabulary                                                   -> clinician review
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime, timedelta, timezone

from pydantic import BaseModel

from .. import audit, lineage, llm
from ..audit import now_iso
from ..db import DB, get_db
from .facts import PatientNotFound, _row_table, as_date, day, patient_exists
from .vocab import known_effects, symptom_vocab

NEW_EXPOSURE_LOOKBACK_DAYS = 90
RECORD_LOOKBACK_DAYS = 365


class ExtractItem(BaseModel):
    span: str
    term: str


class ExtractOut(BaseModel):
    symptoms: list[ExtractItem]


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


# ---------- extract ----------
def _phrases(vocab: list[dict]) -> list[tuple[str, dict]]:
    pairs = [(p, v) for v in vocab for p in [v["term"], *v["synonyms"]]]
    return sorted(pairs, key=lambda x: -len(x[0]))  # longest first: "high temperature" before "temperature"


def _stub_extract(text: str, vocab: list[dict]) -> ExtractOut:
    lower, taken, found = text.lower(), [], []
    for phrase, entry in _phrases(vocab):
        for m in re.finditer(rf"(?<![\w]){re.escape(phrase)}(?![\w])", lower):
            if any(m.start() < e and s < m.end() for s, e in taken):
                continue
            taken.append((m.start(), m.end()))
            found.append((m.start(), ExtractItem(span=text[m.start():m.end()], term=entry["term"])))
    return ExtractOut(symptoms=[item for _, item in sorted(found, key=lambda x: x[0])])


def extract(text: str, vocab: list[dict]) -> tuple[list[ExtractItem], dict]:
    result = llm.call(purpose="symptoms.extract", prompt_file="symptom_extract.md",
                      variables={"terms": ", ".join(v["term"] for v in vocab), "text": text},
                      output_model=ExtractOut, stub=lambda: _stub_extract(text, vocab), effort="low")
    if not result.ok:  # LLM down: the keyword extractor still works, and the audit records why
        items, meta = _stub_extract(text, vocab).symptoms, {**result.meta, "fallback": "keyword"}
    else:
        items, meta = result.parsed.symptoms, result.meta
    verified, lower = [], text.lower()
    for item in items:
        i = lower.find(item.span.strip().lower())
        if item.span.strip() and i >= 0:  # spans must be verbatim; anything else is dropped
            verified.append(ExtractItem(span=text[i:i + len(item.span.strip())], term=item.term.strip().lower()))
    return verified, meta


def map_term(item: ExtractItem, vocab: list[dict]) -> dict | None:
    for v in vocab:
        if item.term == v["term"] or item.term in v["synonyms"]:
            return v
    span = item.span.lower()
    return next((v for phrase, v in _phrases(vocab) if phrase == span), None)


# ---------- classify ----------
def _exposures(db: DB, patient_id: str, effects: list[dict]) -> list[dict]:
    rows = [{"system": "CVX", "code": r["concept_code"], "description": r["description"], "date": as_date(r["d"]),
             "row_id": r["row_id"]} for r in db.query(
        "SELECT row_id, imm_date AS d, concept_code, description FROM curated.immunizations WHERE patient_id = ?", [patient_id])]
    rows += [{"system": "RxNorm", "code": r["concept_code"], "description": r["description"], "date": as_date(r["d"]),
              "row_id": r["row_id"]} for r in db.query(
        "SELECT row_id, start_ts AS d, concept_code, description FROM curated.medications WHERE patient_id = ?", [patient_id])]
    labels = {(e["product_system"], e["product_code"]): e["product_name"] for e in effects}
    for r in rows:
        name = labels.get((r["system"], r["code"]))
        r["label"] = (name if name and "(" in name else f"{name} ({r['system']} {r['code']})") if name else \
            f"{r['description']} ({r['system']} {r['code']})"
        r["known_product"] = name is not None
    return sorted([r for r in rows if r["date"]], key=lambda r: r["date"], reverse=True)


def _record_match(db: DB, patient_id: str, entry: dict | None, term: str, onset: date) -> dict | None:
    words = [term] + (entry["synonyms"] if entry else [])
    for r in db.query("SELECT row_id, start_date, stop_date, concept_code, description FROM curated.conditions "
                      "WHERE patient_id = ? ORDER BY start_date DESC", [patient_id]):
        start, stop = as_date(r["start_date"]), as_date(r["stop_date"])
        if start and start > onset:
            continue
        if stop and stop < onset - timedelta(days=RECORD_LOOKBACK_DAYS):
            continue
        desc = (r["description"] or "").lower()
        if (entry and entry["snomed_code"] and entry["snomed_code"] == r["concept_code"]) or \
                any(re.search(rf"(?<![\w]){re.escape(w)}(?![\w])", desc) for w in words):
            return r
    return None


def classify(db: DB, patient_id: str, item: ExtractItem, entry: dict | None, onset: date,
             exposures: list[dict], effects: list[dict]) -> dict:
    term = entry["term"] if entry else item.term
    base = {"span": item.span, "term": term, "snomed_code": entry["snomed_code"] if entry else None,
            "exposure_code": None, "exposure_label": None, "exposure_date": None}
    if entry:
        for exp in exposures:
            effect = next((e for e in effects if e["product_system"] == exp["system"] and e["product_code"] == exp["code"]
                           and e["effect_term"].lower() == term), None)
            if effect is None:
                continue
            days = (onset - exp["date"]).days
            if 0 <= days <= int(effect["window_days"]):
                return {**base, "classification": "EXPECTED", "review_status": "not_required",
                        "exposure_code": exp["code"], "exposure_label": exp["label"], "exposure_date": day(exp["date"]),
                        "reason": f"Listed side effect of {exp['label']}; dose {day(exp['date'])} is {days} day(s) before "
                                  f"onset, within the {int(effect['window_days'])}-day window",
                        "evidence": [{"kind": "known_effect", "id": effect["effect_id"], "source_url": effect["source_url"]},
                                     {"kind": "row", "id": exp["row_id"]}]}
    record = _record_match(db, patient_id, entry, term, onset)
    if record:
        return {**base, "classification": "IN_RECORD", "review_status": "not_required",
                "reason": f"Already in the patient's record: {record['description']} (since {day(record['start_date'])})",
                "evidence": [{"kind": "row", "id": record["row_id"]}]}

    recent = [e for e in exposures if 0 <= (onset - e["date"]).days <= NEW_EXPOSURE_LOOKBACK_DAYS]
    recent.sort(key=lambda e: (not e["known_product"], -e["date"].toordinal()))
    exp = recent[0] if recent else None
    context = f"Not a listed side effect of {exp['label']} and not in the patient's record" if exp else \
        "No vaccine or medicine in the 90 days before onset, and not in the patient's record"
    if exp:
        base.update(exposure_code=exp["code"], exposure_label=exp["label"], exposure_date=day(exp["date"]))
    if entry is None:
        return {**base, "classification": "UNMAPPED", "review_status": "pending",
                "reason": f"Couldn't map '{item.span}' to the symptom vocabulary. {context}",
                "evidence": [{"kind": "row", "id": exp["row_id"]}] if exp else []}
    return {**base, "classification": "NEW", "review_status": "pending", "reason": context,
            "evidence": [{"kind": "row", "id": exp["row_id"]}] if exp else []}


# ---------- public ----------
def submit_report(patient_id: str, text: str, onset_date: date | None = None, db: DB | None = None) -> dict:
    db = db or get_db()
    if not patient_exists(db, patient_id):
        raise PatientNotFound(patient_id)
    onset = onset_date or datetime.now(timezone.utc).date()
    vocab, effects = symptom_vocab(db), known_effects(db)
    report_id, now = _new_id("RPT"), now_iso()
    db.insert_rows("community.reports", [{"report_id": report_id, "patient_id": patient_id, "report_text": text,
                                          "onset_date": onset, "submitted_at": now}])
    items, meta = extract(text, vocab)
    exposures = _exposures(db, patient_id, effects)

    symptoms, seen = [], set()
    for item in items:
        entry = map_term(item, vocab)
        key = entry["term"] if entry else item.term
        if key in seen:
            continue
        seen.add(key)
        s = classify(db, patient_id, item, entry, onset, exposures, effects)
        s["symptom_id"] = _new_id("SYM")
        symptoms.append(s)

    db.insert_rows("community.symptoms", [{
        "symptom_id": s["symptom_id"], "report_id": report_id, "patient_id": patient_id, "span": s["span"],
        "term": s["term"], "snomed_code": s["snomed_code"], "classification": s["classification"], "reason": s["reason"],
        "evidence_json": json.dumps(s["evidence"]), "exposure_code": s["exposure_code"],
        "exposure_label": s["exposure_label"], "exposure_date": s["exposure_date"], "onset_date": onset,
        "review_status": s["review_status"], "reviewed_by": None, "reviewed_at": None, "review_note": None,
        "created_at": now} for s in symptoms])

    lineage.add(report_id, "report", [(patient_id, "curated.patients")], transform="patient.report", db=db)
    for s in symptoms:
        sources = [(report_id, "report")] + [(e["id"], "ref.known_effects" if e["kind"] == "known_effect" else _row_table(e["id"]))
                                             for e in s["evidence"]]
        lineage.add(s["symptom_id"], "symptom", sources, transform="symptoms.extract+classify", agent="symptom_extractor",
                    model=meta.get("model"), prompt_hash=meta.get("prompt_hash"), db=db)

    counts = {c: sum(1 for s in symptoms if s["classification"] == c) for c in ("EXPECTED", "IN_RECORD", "NEW", "UNMAPPED")}
    seq = audit.append(f"patient:{patient_id}", "report.submitted", report_id, {
        "symptoms": len(symptoms), **counts, "onset_date": day(onset), "extractor_model": meta.get("model"),
        "extractor_fallback": meta.get("fallback"), "extractor_error": meta.get("error")}, db=db)
    for s in symptoms:
        if s["review_status"] == "pending":
            seq = audit.append("system:symptoms", "symptom.flagged", s["symptom_id"], {
                "report_id": report_id, "term": s["term"], "classification": s["classification"], "reason": s["reason"]}, db=db)

    return {"report_id": report_id, "patient_id": patient_id, "audit_seq": seq, "symptoms": [{
        "symptom_id": s["symptom_id"], "span": s["span"], "term": s["term"], "snomed_code": s["snomed_code"],
        "classification": s["classification"], "reason": s["reason"], "evidence": s["evidence"],
        "review_status": s["review_status"]} for s in symptoms]}
