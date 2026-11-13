"""Facts engine: deterministic statements about one patient, each citing the curated rows it came from.

The SQL is Dev A's db/facts.sql, run through app.factsql.compute_facts (one '-- name:' block per kind).
This module adds what the clinical engine needs on top: stable fact IDs, a fixed sentence for NEXT_STEP facts,
ordering and caps per kind, storage in clinical.facts, and lineage fact -> curated rows.

The LLM never sees raw rows, only these facts. Values are already rounded the way they may be written, so the
critic can check every number and date in a sentence against the facts it cites.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime

from .. import lineage
from ..audit import now_iso
from ..db import DB, get_db
from ..factsql import ROW_TABLES, compute_facts
from ..schema import table_exists

KINDS = ["LAB_TREND", "CONDITION", "MEDICATION", "IMMUNIZATION", "ENCOUNTER", "CAREPLAN", "ALLERGY", "NEXT_STEP"]
MAX_PER_KIND = {"LAB_TREND": 8, "CONDITION": 8, "MEDICATION": 6, "IMMUNIZATION": 4, "ENCOUNTER": 3,
                "CAREPLAN": 4, "ALLERGY": 4, "NEXT_STEP": 4}
COVID_VACCINE_CODES = ("207", "208", "210", "212", "213", "217", "218", "219", "221", "228", "229", "300")


class PatientNotFound(Exception):
    pass


# ---------- helpers (also used by patients.py and symptoms.py) ----------
def day(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.strftime("%Y-%m-%d")
    text = str(value).strip()
    return text[:10] if text else None


def as_date(value) -> date | None:
    d = day(value)
    return date.fromisoformat(d) if d else None


def month_name(d: str | None) -> str:
    return datetime.strptime(d, "%Y-%m-%d").strftime("%B %Y") if d else "an unknown date"


def fact_id(patient_id: str, kind: str, key: str) -> str:
    return "FCT-" + hashlib.sha1(f"{patient_id}|{kind}|{key}".encode()).hexdigest()[:12]


def _row_table(row_id: str) -> str:
    return ROW_TABLES.get(row_id.split("-")[0], "curated")


def patient_exists(db: DB, patient_id: str) -> bool:
    return bool(db.query("SELECT 1 AS x FROM curated.patients WHERE patient_id = ?", [patient_id]))


# ---------- adapter over Dev A's facts ----------
def next_step_text(data: dict) -> str:
    """The patient-facing sentence for a NEXT_STEP fact. Fixed here, so the LLM can't turn it into advice."""
    if data.get("rule_name") == "DISCUSS_LAB" and data.get("lab"):
        lab = data["lab"]
        return f"Talk to your care team about your {lab['plain_name']} result from {month_name(lab.get('date'))}."
    plan = data.get("careplan") or {}
    who = f" with {plan['provider_name']}" if plan.get("provider_name") else ""
    return f"Keep following your care plan \"{plan.get('description', 'from your record')}\"{who}."


def _adapt(patient_id: str, raw: dict) -> dict:
    data = dict(raw["data"])
    if raw["kind"] == "NEXT_STEP":
        data["text"] = next_step_text(data)
    key = f"{raw['block']}|{data.get('rule_name', '')}|{','.join(raw['source_row_ids'])}"
    return {"fact_id": fact_id(patient_id, raw["kind"], key), "kind": raw["kind"], "block": raw["block"],
            "data": data, "source_row_ids": raw["source_row_ids"]}


def _order(facts: list[dict]) -> list[dict]:
    by_kind: dict[str, list[dict]] = {k: [] for k in KINDS}
    for f in facts:
        by_kind.setdefault(f["kind"], []).append(f)
    labs = by_kind["LAB_TREND"]
    labs.sort(key=lambda f: (f["data"].get("latest") or {}).get("date") or "", reverse=True)  # newest first
    labs.sort(key=lambda f: (f["data"].get("latest") or {}).get("flag") == "NORMAL")         # out of range first
    return [f for k in KINDS for f in by_kind[k][:MAX_PER_KIND[k]]]


# ---------- public ----------
def compute(patient_id: str, db: DB | None = None) -> list[dict]:
    db = db or get_db()
    if not table_exists(db, "curated.patients") or not patient_exists(db, patient_id):
        raise PatientNotFound(patient_id)
    facts = _order([_adapt(patient_id, raw) for raw in compute_facts(patient_id, db)])
    _store(db, patient_id, facts)
    return facts


def _store(db: DB, patient_id: str, facts: list[dict]) -> None:
    db.execute("DELETE FROM clinical.facts WHERE patient_id = ?", [patient_id])
    if not facts:
        return
    now = now_iso()
    db.insert_rows("clinical.facts", [{
        "fact_id": f["fact_id"], "patient_id": patient_id, "kind": f["kind"],
        "data_json": json.dumps(f["data"], sort_keys=True, ensure_ascii=False),
        "source_row_ids": ",".join(f["source_row_ids"]), "computed_at": now} for f in facts])
    ids = [f["fact_id"] for f in facts]
    known = {r["derived_id"] for r in db.query(
        f"SELECT DISTINCT derived_id FROM gov.lineage_edges WHERE derived_id IN ({', '.join('?' for _ in ids)})", ids)}
    for f in facts:
        if f["fact_id"] not in known:
            lineage.add(f["fact_id"], "fact", [(sid, _row_table(sid)) for sid in f["source_row_ids"]],
                        transform=f"facts.sql:{f['block']}", db=db)
