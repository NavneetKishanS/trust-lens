"""Facts engine: deterministic statements about one patient, each citing the curated rows it came from.

The LLM never sees raw rows, only these facts. A fact's values are already rounded the way they may be written,
so the critic can check every number and date in a sentence against the facts it cites.

If Dev A's db/facts.sql has a `-- name: <kind>` block (SELECT kind, data_json, source_row_ids with ? = patient_id),
it replaces the Python builder for that kind.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta

from .. import config, lineage
from ..audit import now_iso
from ..db import DB, get_db
from ..schema import table_exists
from .ranges import lab_ranges

FACTS_SQL = config.REPO_ROOT / "db" / "facts.sql"
KINDS = ["LAB_TREND", "CONDITION", "MEDICATION", "IMMUNIZATION", "ENCOUNTER", "CAREPLAN", "ALLERGY", "NEXT_STEP"]
MAX_PER_KIND = {"LAB_TREND": 8, "CONDITION": 8, "MEDICATION": 6, "IMMUNIZATION": 4, "ENCOUNTER": 3,
                "CAREPLAN": 4, "ALLERGY": 4, "NEXT_STEP": 4}
COVID_VACCINE_CODES = ("207", "208", "210", "212", "213", "217", "218", "219", "221", "228", "229", "300")


class PatientNotFound(Exception):
    pass


# ---------- helpers ----------
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


def num(value: float):
    """Round the way a sentence may write it: one decimal, integers without '.0'."""
    r = round(float(value), 1)
    return int(r) if r == int(r) else r


def flag(value: float, rng: dict) -> str:
    if value < rng["low"]:
        return "LOW"
    if value > rng["high"]:
        return "HIGH"
    return "NORMAL"


def fact_id(patient_id: str, kind: str, key: str) -> str:
    return "FCT-" + hashlib.sha1(f"{patient_id}|{kind}|{key}".encode()).hexdigest()[:12]


def _fact(patient_id: str, kind: str, key: str, data: dict, sources: list[str]) -> dict:
    return {"fact_id": fact_id(patient_id, kind, key), "kind": kind, "data": data, "source_row_ids": sources}


# ---------- builders ----------
def _rows(db: DB, sql: str, patient_id: str) -> list[dict]:
    return db.query(sql, [patient_id])


def reference_date(db: DB, patient_id: str) -> date:
    """'Today' for this patient: the latest encounter or observation (Synthea records end at generation time)."""
    dates = [as_date(r["d"]) for r in db.query(
        "SELECT MAX(start_ts) AS d FROM curated.encounters WHERE patient_id = ? "
        "UNION ALL SELECT MAX(obs_date) AS d FROM curated.observations WHERE patient_id = ?", [patient_id, patient_id])]
    dates = [d for d in dates if d]
    return max(dates) if dates else date.today()


def lab_trends(db: DB, pid: str, ranges: dict) -> list[dict]:
    rows = _rows(db, "SELECT row_id, obs_date, concept_code, description, value_num, units FROM curated.observations "
                     "WHERE patient_id = ? AND value_num IS NOT NULL ORDER BY obs_date DESC, row_id", pid)
    by_code: dict[str, list[dict]] = {}
    for r in rows:
        if r["concept_code"] in ranges:
            by_code.setdefault(r["concept_code"], []).append(r)
    facts = []
    for code, obs in by_code.items():
        rng = ranges[code]
        latest = obs[0]
        previous = next((o for o in obs[1:] if day(o["obs_date"]) != day(latest["obs_date"])), None)

        def point(o):
            return {"value": num(o["value_num"]), "date": day(o["obs_date"]), "flag": flag(float(o["value_num"]), rng)}

        data = {"loinc": code, "name": rng["name"], "plain_name": rng["plain_name"], "units": latest["units"] or rng["units"],
                "usual_range": {"low": num(rng["low"]), "high": num(rng["high"])},
                "latest": point(latest), "previous": point(previous) if previous else None}
        if previous:
            a, b = data["previous"]["value"], data["latest"]["value"]
            data["direction"] = "up" if b > a else "down" if b < a else "same"
        sources = [latest["row_id"]] + ([previous["row_id"]] if previous else [])
        facts.append(_fact(pid, "LAB_TREND", code, data, sources))
    facts.sort(key=lambda f: f["data"]["latest"]["date"] or "", reverse=True)    # newest first
    facts.sort(key=lambda f: f["data"]["latest"]["flag"] == "NORMAL")           # then out-of-range first (stable)
    return facts


def conditions(db: DB, pid: str, ref: date) -> list[dict]:
    rows = _rows(db, "SELECT row_id, start_date, stop_date, code_system, concept_code, description FROM curated.conditions "
                     "WHERE patient_id = ? ORDER BY start_date DESC", pid)
    out = []
    for r in rows:
        stop = as_date(r["stop_date"])
        if stop and stop < ref - timedelta(days=730):
            continue
        out.append(_fact(pid, "CONDITION", r["row_id"], {
            "code_system": r["code_system"] or "SNOMED", "code": r["concept_code"], "description": r["description"],
            "onset": day(r["start_date"]), "resolved": day(r["stop_date"]), "active": stop is None}, [r["row_id"]]))
    return out


def medications(db: DB, pid: str, ref: date) -> list[dict]:
    rows = _rows(db, "SELECT row_id, start_ts, stop_ts, concept_code, description, reason_description "
                     "FROM curated.medications WHERE patient_id = ? ORDER BY start_ts DESC", pid)
    out, seen = [], set()
    for r in rows:
        start, stop = as_date(r["start_ts"]), as_date(r["stop_ts"])
        recent = (start and start >= ref - timedelta(days=365)) or (stop and stop >= ref - timedelta(days=365))
        if not (stop is None or recent) or r["concept_code"] in seen:
            continue
        seen.add(r["concept_code"])
        status = "active" if stop is None else "stopped"
        out.append(_fact(pid, "MEDICATION", r["row_id"], {
            "code_system": "RxNorm", "code": r["concept_code"], "description": r["description"], "status": status,
            "started": day(r["start_ts"]), "stopped": day(r["stop_ts"]), "reason": r["reason_description"]}, [r["row_id"]]))
    return out


def immunizations(db: DB, pid: str, ref: date) -> list[dict]:
    rows = _rows(db, "SELECT row_id, imm_date, concept_code, description FROM curated.immunizations "
                     "WHERE patient_id = ? ORDER BY imm_date DESC", pid)
    return [_fact(pid, "IMMUNIZATION", r["row_id"], {
        "code_system": "CVX", "code": r["concept_code"], "description": r["description"], "date": day(r["imm_date"]),
        "covid_vaccine": r["concept_code"] in COVID_VACCINE_CODES}, [r["row_id"]])
        for r in rows if as_date(r["imm_date"]) and as_date(r["imm_date"]) >= ref - timedelta(days=730)]


def encounters(db: DB, pid: str) -> list[dict]:
    rows = _rows(db, "SELECT row_id, start_ts, encounter_class, concept_code, description, reason_description, "
                     "provider_name, organization_name FROM curated.encounters WHERE patient_id = ? ORDER BY start_ts DESC", pid)
    return [_fact(pid, "ENCOUNTER", r["row_id"], {
        "date": day(r["start_ts"]), "encounter_class": r["encounter_class"], "code": r["concept_code"],
        "description": r["description"], "reason": r["reason_description"], "provider": r["provider_name"],
        "organization": r["organization_name"]}, [r["row_id"]]) for r in rows]


def careplans(db: DB, pid: str) -> list[dict]:
    rows = _rows(db, "SELECT c.row_id, c.start_date, c.concept_code, c.description, c.reason_description, "
                     "e.row_id AS enc_row_id, e.provider_name, e.organization_name FROM curated.careplans c "
                     "LEFT JOIN curated.encounters e ON e.encounter_id = c.encounter_id "
                     "WHERE c.patient_id = ? AND c.stop_date IS NULL ORDER BY c.start_date DESC", pid)
    return [_fact(pid, "CAREPLAN", r["row_id"], {
        "code_system": "SNOMED", "code": r["concept_code"], "description": r["description"], "started": day(r["start_date"]),
        "reason": r["reason_description"], "provider": r["provider_name"], "organization": r["organization_name"]},
        [r["row_id"]] + ([r["enc_row_id"]] if r["enc_row_id"] else [])) for r in rows]


def allergies(db: DB, pid: str) -> list[dict]:
    if not table_exists(db, "curated.allergies"):
        return []
    rows = _rows(db, "SELECT row_id, start_date, concept_code, description, category FROM curated.allergies "
                     "WHERE patient_id = ? AND stop_date IS NULL", pid)
    return [_fact(pid, "ALLERGY", r["row_id"], {"code_system": "SNOMED", "code": r["concept_code"],
                                                "description": r["description"], "category": r["category"],
                                                "since": day(r["start_date"])}, [r["row_id"]]) for r in rows]


def next_steps(pid: str, labs: list[dict], encs: list[dict], plans: list[dict]) -> list[dict]:
    """Rules only. The text is fixed here so the LLM can't turn it into advice."""
    out = []
    last_visit = max((e["data"]["date"] for e in encs if e["data"]["date"]), default=None)
    for lab in labs:
        latest = lab["data"]["latest"]
        if latest["flag"] != "NORMAL" and (last_visit is None or last_visit <= latest["date"]):
            month = datetime.strptime(latest["date"], "%Y-%m-%d").strftime("%B %Y")
            out.append(_fact(pid, "NEXT_STEP", f"lab:{lab['data']['loinc']}", {
                "rule": "out_of_range_lab_without_later_visit", "date": latest["date"],
                "text": f"Talk to your care team about your {lab['data']['plain_name']} result from {month}."},
                lab["source_row_ids"][:1]))
    for plan in plans:
        d = plan["data"]
        who = f" with {d['provider']}" if d.get("provider") else ""
        out.append(_fact(pid, "NEXT_STEP", f"plan:{plan['fact_id']}", {
            "rule": "active_care_plan", "date": d["started"],
            "text": f"Keep following your care plan \"{d['description']}\"{who}."}, plan["source_row_ids"]))
    return out


def _from_sql_blocks(db: DB, pid: str) -> dict[str, list[dict]]:
    """Dev A's blocks return either a data_json column or plain data columns (packed by app.factsql).
    A block whose tables aren't loaded (e.g. the dev fixture has no ref.*) keeps the Python builder."""
    if not FACTS_SQL.exists():
        return {}
    from ..factsql import pack_row, tables_in

    out: dict[str, list[dict]] = {}
    for name, sql in DB.named_blocks(FACTS_SQL).items():
        kind = name.upper()
        if kind not in KINDS or not all(table_exists(db, t) for t in tables_in(sql)):
            continue
        rows = db.query(sql, [pid] * sql.count("?"))
        out[kind] = []
        for r in rows:
            data = json.loads(r["data_json"]) if "data_json" in r else pack_row(r)["data"]
            sources = [s.strip() for s in str(r["source_row_ids"]).split(",") if s.strip()]
            out[kind].append(_fact(pid, kind, r["source_row_ids"], data, sources))
    return out


# ---------- public ----------
def patient_exists(db: DB, patient_id: str) -> bool:
    return bool(db.query("SELECT 1 AS x FROM curated.patients WHERE patient_id = ?", [patient_id]))


def compute(patient_id: str, db: DB | None = None) -> list[dict]:
    db = db or get_db()
    if not table_exists(db, "curated.patients") or not patient_exists(db, patient_id):
        raise PatientNotFound(patient_id)
    ref = reference_date(db, patient_id)
    ranges = lab_ranges(db)
    labs = lab_trends(db, patient_id, ranges)
    encs = encounters(db, patient_id)
    plans = careplans(db, patient_id)
    built = {
        "LAB_TREND": labs, "CONDITION": conditions(db, patient_id, ref), "MEDICATION": medications(db, patient_id, ref),
        "IMMUNIZATION": immunizations(db, patient_id, ref), "ENCOUNTER": encs, "CAREPLAN": plans,
        "ALLERGY": allergies(db, patient_id), "NEXT_STEP": next_steps(patient_id, labs, encs, plans),
    }
    built.update(_from_sql_blocks(db, patient_id))
    facts = [f for kind in KINDS for f in built[kind][:MAX_PER_KIND[kind]]]
    _store(db, patient_id, facts)
    return facts


def _store(db: DB, patient_id: str, facts: list[dict]) -> None:
    db.execute("DELETE FROM clinical.facts WHERE patient_id = ?", [patient_id])
    now = now_iso()
    db.insert_rows("clinical.facts", [{
        "fact_id": f["fact_id"], "patient_id": patient_id, "kind": f["kind"],
        "data_json": json.dumps(f["data"], sort_keys=True, ensure_ascii=False),
        "source_row_ids": ",".join(f["source_row_ids"]), "computed_at": now} for f in facts])
    if not facts:
        return
    ids = [f["fact_id"] for f in facts]
    known = {r["derived_id"] for r in db.query(
        f"SELECT DISTINCT derived_id FROM gov.lineage_edges WHERE derived_id IN ({', '.join('?' for _ in ids)})", ids)}
    for f in facts:
        if f["fact_id"] not in known:
            lineage.add(f["fact_id"], "fact", [(sid, _row_table(sid)) for sid in f["source_row_ids"]],
                        transform=f"facts:{f['kind'].lower()}", db=db)


ROW_TABLES = {"PAT": "curated.patients", "ENC": "curated.encounters", "CON": "curated.conditions",
              "OBS": "curated.observations", "MED": "curated.medications", "IMM": "curated.immunizations",
              "CPL": "curated.careplans", "ALG": "curated.allergies", "PRC": "curated.procedures"}


def _row_table(row_id: str) -> str:
    return ROW_TABLES.get(row_id.split("-")[0], "curated")
