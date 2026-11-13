"""Section layout per audience and the deterministic sentence templates used in stub mode."""
from __future__ import annotations

from datetime import datetime

SECTIONS = {
    "patient": {
        "LAB_TREND": "Your lab results", "ENCOUNTER": "Your visits and care plans", "CAREPLAN": "Your visits and care plans",
        "MEDICATION": "Medicines and vaccines", "IMMUNIZATION": "Medicines and vaccines", "ALLERGY": "Medicines and vaccines",
        "NEXT_STEP": "Next steps",
    },
    "physician": {
        "LAB_TREND": "Labs (LOINC)", "CONDITION": "Active problems (SNOMED CT)", "MEDICATION": "Medications (RxNorm)",
        "IMMUNIZATION": "Immunizations (CVX)", "ENCOUNTER": "Encounters", "CAREPLAN": "Care plans",
        "NEXT_STEP": "Care plans", "ALLERGY": "Allergies",
    },
}
SECTION_ORDER = {
    "patient": ["Your lab results", "Your visits and care plans", "Medicines and vaccines", "Next steps"],
    "physician": ["Labs (LOINC)", "Active problems (SNOMED CT)", "Medications (RxNorm)", "Immunizations (CVX)",
                  "Encounters", "Care plans", "Allergies"],
}
FLAG_TEXT = {"HIGH": "above the usual range", "LOW": "below the usual range", "NORMAL": "in the usual range"}


def month(d: str | None) -> str:
    return datetime.strptime(d, "%Y-%m-%d").strftime("%B %Y") if d else "an unknown date"


def long_day(d: str | None) -> str:
    return f"{int(d[8:10])} {datetime.strptime(d, '%Y-%m-%d').strftime('%B %Y')}" if d else "an unknown date"


def facts_for(audience: str, facts: list[dict]) -> list[dict]:
    return [f for f in facts if f["kind"] in SECTIONS[audience]]


def _patient(f: dict) -> str:
    d = f["data"]
    k = f["kind"]
    if k == "LAB_TREND":
        lat, prev, u = d["latest"], d.get("previous"), d["units"]
        now = f"{lat['value']} {u} in {month(lat['date'])}, {FLAG_TEXT[lat['flag']]}"
        if not prev:
            return f"Your {d['plain_name']} was {now}."
        return (f"Your {d['plain_name']} was {prev['value']} {u} in {month(prev['date'])}, {FLAG_TEXT[prev['flag']]}. "
                f"In {month(lat['date'])} it was {lat['value']} {u}, {FLAG_TEXT[lat['flag']]}.")
    if k == "ENCOUNTER":
        who = f" with {d['provider']}" if d.get("provider") else ""
        where = f" at {d['organization']}" if d.get("organization") else ""
        return f"On {long_day(d['date'])} you had a visit{who}{where}: {d['description']}."
    if k == "CAREPLAN":
        return f"Your record lists a care plan, \"{d['description']}\", started in {month(d['started'])}."
    if k == "MEDICATION":
        if d["status"] == "active":
            return f"Your record lists {d['description']}, started in {month(d['started'])}."
        return f"{d['description']} was stopped in {month(d['stopped'])}."
    if k == "IMMUNIZATION":
        return f"You received a vaccine on {long_day(d['date'])}: {d['description']}."
    if k == "ALLERGY":
        return f"Your record lists an allergy: {d['description']}."
    if k == "NEXT_STEP":
        return d["text"]
    raise ValueError(k)


def _physician(f: dict) -> str:
    d = f["data"]
    k = f["kind"]
    if k == "LAB_TREND":
        lat, prev, u = d["latest"], d.get("previous"), d["units"]
        head = f"{d['name']} (LOINC {d['loinc']})"
        if not prev:
            return f"{head}: {lat['value']} {u} on {lat['date']} ({lat['flag'].lower()})."
        return (f"{head}: {prev['value']} {u} on {prev['date']} ({prev['flag'].lower()}) to {lat['value']} {u} "
                f"on {lat['date']} ({lat['flag'].lower()}).")
    if k == "CONDITION":
        state = "active" if d["active"] else f"resolved {d['resolved']}"
        return f"{d['description']} (SNOMED {d['code']}), onset {d['onset']}, {state}."
    if k == "MEDICATION":
        end = "ongoing" if d["status"] == "active" else f"stopped {d['stopped']}"
        why = f", for {d['reason']}" if d.get("reason") else ""
        return f"{d['description']} (RxNorm {d['code']}), started {d['started']}, {end}{why}."
    if k == "IMMUNIZATION":
        return f"{d['description']} (CVX {d['code']}) on {d['date']}."
    if k == "ENCOUNTER":
        why = f", reason: {d['reason']}" if d.get("reason") else ""
        who = f", {d['provider']}" if d.get("provider") else ""
        return f"{d['date']}: {d['encounter_class']} encounter, {d['description']}{who}{why}."
    if k == "CAREPLAN":
        why = f" for {d['reason']}" if d.get("reason") else ""
        return f"Active care plan: {d['description']} (SNOMED {d['code']}){why}, since {d['started']}."
    if k == "NEXT_STEP":
        return f"Open item for patient communication: {d['text']}"
    if k == "ALLERGY":
        return f"Allergy: {d['description']} (SNOMED {d['code']}), {d['category']}."
    raise ValueError(k)


def stub_sentence(audience: str, fact: dict) -> str:
    return _patient(fact) if audience == "patient" else _physician(fact)
