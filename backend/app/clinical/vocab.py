"""Symptom vocabulary and known side effects.

Reads Dev A's ref.symptom_vocab / ref.known_effects when they exist; until then uses the fallbacks below.
SNOMED codes are only given where we're sure; the rest stay None (never guess codes).
The known-effect lists follow the common reactions in the Spikevax / Comirnaty product information;
Dev A replaces them with ref.known_effects rows that carry the official source URL.
"""
from __future__ import annotations

from ..db import DB
from ..schema import table_exists

# term, synonyms, snomed_code
SYMPTOM_VOCAB: list[tuple[str, list[str], str | None]] = [
    ("fatigue", ["tired", "tiredness", "exhausted", "exhaustion", "no energy", "worn out", "fatigued"], "84229001"),
    ("headache", ["head hurts", "head ache", "headaches", "migraine"], "25064002"),
    ("fever", ["temperature", "feverish", "high temperature"], "386661006"),
    ("chills", ["shivering", "shivers", "chilly"], "43724002"),
    ("muscle pain", ["muscle ache", "muscle aches", "aching muscles", "sore muscles", "myalgia", "body aches"], "68962001"),
    ("joint pain", ["knee pain", "knee hurts", "aching joints", "sore joints", "joints hurt", "arthralgia"], "57676002"),
    ("nausea", ["feel sick", "feeling sick", "nauseous", "queasy"], "422587007"),
    ("vomiting", ["threw up", "throwing up", "vomit", "vomited"], "422400008"),
    ("injection site pain", ["sore arm", "arm hurts", "arm is sore", "pain at the injection site", "pain where i got the shot"], None),
    ("injection site swelling", ["swollen arm", "swelling at the injection site", "arm is swollen"], None),
    ("injection site redness", ["red arm", "redness at the injection site", "arm is red"], None),
    ("swollen lymph nodes", ["swollen armpit", "lump in my armpit", "swollen glands", "armpit swelling"], None),
    ("dizziness", ["dizzy", "lightheaded", "light-headed", "vertigo"], "404640003"),
    ("blurred vision", ["blurry vision", "blurry eyes", "vision is blurry", "can't see clearly", "blurred eyesight"], "111516008"),
    ("tinnitus", ["ringing in my ears", "ringing in the ears", "ears ringing", "buzzing in my ears"], "60862001"),
    ("palpitations", ["heart racing", "racing heart", "heart pounding", "heart flutter", "irregular heartbeat"], "80313002"),
    ("chest pain", ["chest hurts", "pain in my chest", "chest tightness"], None),
    ("shortness of breath", ["short of breath", "breathless", "hard to breathe", "can't breathe properly"], None),
    ("cough", ["coughing"], "49727002"),
    ("rash", ["skin rash", "hives", "itchy skin", "spots on my skin"], "271807003"),
    ("diarrhea", ["diarrhoea", "loose stools", "runny tummy"], "62315008"),
    ("insomnia", ["can't sleep", "cannot sleep", "trouble sleeping", "sleepless"], None),
    ("hair loss", ["losing hair", "hair falling out"], None),
    ("high blood pressure", ["hypertension", "blood pressure is high", "high bp"], None),
    ("numbness", ["tingling", "pins and needles", "numb"], None),
    ("loss of appetite", ["not hungry", "no appetite"], None),
]

MODERNA = ("CVX", "207", "Moderna (CVX 207)")
PFIZER = ("CVX", "208", "Pfizer-BioNTech (CVX 208)")
_COMMON_MRNA = ["injection site pain", "injection site swelling", "injection site redness", "fatigue", "headache",
                "muscle pain", "joint pain", "chills", "nausea", "vomiting", "fever", "swollen lymph nodes"]
FALLBACK_SOURCE = "Common reactions listed in the product information (fallback list; Dev A adds the official URL)"


def symptom_vocab(db: DB) -> list[dict]:
    if table_exists(db, "ref.symptom_vocab"):
        rows = db.query("SELECT term, synonyms, snomed_code FROM ref.symptom_vocab")
        return [{"term": r["term"].lower(), "synonyms": [s.strip().lower() for s in (r["synonyms"] or "").split(";") if s.strip()],
                 "snomed_code": r["snomed_code"]} for r in rows]
    return [{"term": t, "synonyms": syn, "snomed_code": code} for t, syn, code in SYMPTOM_VOCAB]


def known_effects(db: DB) -> list[dict]:
    if table_exists(db, "ref.known_effects"):
        return db.query("SELECT effect_id, product_system, product_code, product_name, effect_term, window_days, "
                        "source_title, source_url FROM ref.known_effects")
    out = []
    for system, code, name in (MODERNA, PFIZER):
        for term in _COMMON_MRNA:
            out.append({"effect_id": f"KE-{code}-{term.replace(' ', '-')}", "product_system": system, "product_code": code,
                        "product_name": name, "effect_term": term, "window_days": 14,
                        "source_title": FALLBACK_SOURCE, "source_url": None})
    return out
