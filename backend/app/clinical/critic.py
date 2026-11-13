"""Deterministic critic for summary sentences (shared §8). No LLM.

Checks, per sentence:
  1. every cited fact_id exists for this patient
  2. every number in the text appears in a cited fact (±0.1)
  3. every date / month in the text matches a date in a cited fact
  4. no banned phrase for the audience (§8a)
  5. patient audience: no medical term that the cited facts don't contain
"""
from __future__ import annotations

import json
import re
from datetime import datetime

MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
DATE_PATTERNS = [
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), lambda m: ("day", f"{m[1]}-{m[2]}-{m[3]}")),
    (re.compile(rf"\b(\d{{1,2}}) ({MONTHS}) (\d{{4}})\b"),
     lambda m: ("day", datetime.strptime(f"{m[1]} {m[2]} {m[3]}", "%d %B %Y").strftime("%Y-%m-%d"))),
    (re.compile(rf"\b({MONTHS}) (\d{{1,2}}), (\d{{4}})\b"),
     lambda m: ("day", datetime.strptime(f"{m[2]} {m[1]} {m[3]}", "%d %B %Y").strftime("%Y-%m-%d"))),
    (re.compile(rf"\b({MONTHS}) (\d{{4}})\b"), lambda m: ("month", datetime.strptime(f"{m[1]} {m[2]}", "%B %Y").strftime("%Y-%m"))),
    (re.compile(r"\b(\d{2})/(\d{4})\b"), lambda m: ("month", f"{m[2]}-{m[1]}")),
]
ISO_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
NUMBER = re.compile(r"\d+(?:\.\d+)?")

BANNED = {
    "patient": ["you have", "you may have", "you seem", "you might", "diagnos", "suffer", "should take", "stop taking",
                "start taking", "increase your", "decrease your", "reduce your", "you must", "you need to take", "dose"],
    "physician": ["you should", "recommend", "consider prescribing", "consider starting", "must ", "should be started",
                  "advise", "suggest"],
}
MEDICAL_TERMS = [
    "diabetes", "diabetic", "prediabetes", "hypertension", "hypertensive", "obesity", "obese", "cancer", "tumor",
    "tumour", "malignan", "infection", "disease", "disorder", "syndrome", "kidney failure", "renal failure",
    "heart failure", "anemia", "anaemia", "asthma", "copd", "depression", "anxiety", "stroke", "myocarditis",
    "pneumonia", "sepsis", "chronic", "hyperlipidemia", "hypercholesterolemia", "arthritis", "osteoporosis",
    "dementia", "fracture", "insulin resistance", "neuropathy", "retinopathy",
]


def _extract_dates(text: str) -> tuple[list[tuple[str, str]], str]:
    """Return [(granularity, value)] and the text with dates blanked out (so their digits aren't read as numbers)."""
    found = []
    for pattern, convert in DATE_PATTERNS:
        def blank(m):
            try:
                found.append(convert(m))
            except ValueError:
                found.append(("invalid", m[0]))
            return " " * len(m[0])
        text = pattern.sub(blank, text)
    return found, text


def _numbers(text: str) -> list[float]:
    return [float(n) for n in NUMBER.findall(re.sub(r"(?<=\d),(?=\d{3})", "", text))]


def check(sentence_text: str, fact_ids: list[str], facts_by_id: dict[str, dict], audience: str) -> dict:
    reasons: list[str] = []
    cited = [facts_by_id[f] for f in fact_ids if f in facts_by_id]
    unknown = [f for f in fact_ids if f not in facts_by_id]
    if not fact_ids:
        reasons.append("no fact cited")
    if unknown:
        reasons.append(f"unknown fact_id(s): {', '.join(unknown)}")

    blob = json.dumps([f["data"] for f in cited], ensure_ascii=False)
    fact_days = set(ISO_DAY.findall(blob))
    fact_months = {d[:7] for d in fact_days}
    _, fact_blob_no_dates = _extract_dates(blob)
    allowed = _numbers(fact_blob_no_dates)

    dates, text_no_dates = _extract_dates(sentence_text)
    for granularity, value in dates:
        if granularity == "invalid":
            reasons.append(f"unreadable date '{value}'")
        elif granularity == "day" and value not in fact_days:
            reasons.append(f"date {value} not in cited facts")
        elif granularity == "month" and value not in fact_months:
            reasons.append(f"month {value} not in cited facts")

    for n in _numbers(text_no_dates):
        if not any(abs(n - a) <= 0.1 for a in allowed):
            reasons.append(f"number {n:g} not in cited facts")

    lower, blob_lower = sentence_text.lower(), blob.lower()
    for phrase in BANNED.get(audience, []):
        # a phrase quoted from the record itself (e.g. "100 mcg/0.5mL dose" in a vaccine name) is not advice
        if phrase in lower and phrase not in blob_lower:
            reasons.append(f"banned phrase for {audience}: '{phrase.strip()}'")
    if audience == "patient":
        for term in MEDICAL_TERMS:
            if term in lower and term not in blob_lower:
                reasons.append(f"medical term '{term}' not in cited facts")

    return {"status": "FLAG" if reasons else "PASS", "reasons": reasons}
