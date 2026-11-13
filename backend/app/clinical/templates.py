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


def _reason(d: dict) -> str | None:
    return (d.get("reason") or {}).get("description")


def _patient(f: dict) -> str:
    """Field names follow Dev A's db/facts.sql columns (a__b nests as {"a": {"b": ...}})."""
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
        who = f" with {d['provider_name']}" if d.get("provider_name") else ""
        where = f" at {d['organization_name']}" if d.get("organization_name") else ""
        return f"On {long_day(d['encounter_date'])} you had a visit{who}{where}: {d['description']}."
    if k == "CAREPLAN":
        return f"Your record lists a care plan, \"{d['description']}\", started in {month(d.get('start_date'))}."
    if k == "MEDICATION":
        if d["status"] == "active":
            return f"Your record lists {d['description']}, started in {month(d.get('start_date'))}."
        return f"{d['description']} was stopped in {month(d.get('stop_date'))}."
    if k == "IMMUNIZATION":
        name = f" ({d['product_name']})" if d.get("product_name") else ""
        return f"You received a vaccine{name} on {long_day(d['imm_date'])}: {d['description']}."
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
        state = "active" if d["status"] == "active" else f"resolved {d.get('stop_date')}"
        return f"{d['description']} (SNOMED {d['snomed']}), onset {d.get('onset_date')}, {state}."
    if k == "MEDICATION":
        end = "ongoing" if d["status"] == "active" else f"stopped {d.get('stop_date')}"
        why = f", for {_reason(d)}" if _reason(d) else ""
        return f"{d['description']} (RxNorm {d['rxnorm']}), started {d.get('start_date')}, {end}{why}."
    if k == "IMMUNIZATION":
        return f"{d['description']} (CVX {d['cvx']}) on {d['imm_date']}."
    if k == "ENCOUNTER":
        why = f", reason: {_reason(d)}" if _reason(d) else ""
        who = f", {d['provider_name']}" if d.get("provider_name") else ""
        return f"{d['encounter_date']}: {d['encounter_class']} encounter, {d['description']}{who}{why}."
    if k == "CAREPLAN":
        why = f" for {_reason(d)}" if _reason(d) else ""
        return f"Active care plan: {d['description']} (SNOMED {d['snomed']}){why}, since {d.get('start_date')}."
    if k == "NEXT_STEP":
        return f"Open item for patient communication: {d['text']}"
    if k == "ALLERGY":
        return f"Allergy: {d['description']} (SNOMED {d['concept_code']}), {d.get('category')}."
    raise ValueError(k)


def stub_sentence(audience: str, fact: dict) -> str:
    return _patient(fact) if audience == "patient" else _physician(fact)
