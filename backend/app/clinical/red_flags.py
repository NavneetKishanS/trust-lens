"""Red-flag symptoms: deterministic, never decided by the LLM.

A red flag doesn't change the classification (shared §8). It forces clinician review, puts the item at the top of the
queue, and shows the patient a fixed safety message. Matching runs on the extracted term/span AND on the raw report
text, so a symptom the extractor missed still raises the flag. Demo list, not a clinical triage protocol.
"""
from __future__ import annotations

import re

URGENT_PREFIX = "URGENT: "

# Fixed text (Germany: 112 emergency, 116 117 on-call doctors). Never generated.
URGENT_ADVICE = ("Some of what you describe can be serious. If it is happening now or getting worse, call 112 "
                 "(emergency) straight away. For urgent but not life-threatening problems, call 116 117 "
                 "(on-call doctors). Your care team has been told, but they may not see this right away.")

# vocabulary term -> patterns that mean the same thing in patient words
RED_FLAGS: dict[str, list[str]] = {
    "chest pain": [r"chest (?:pain|tightness|pressure)", r"pain in (?:my|the) chest", r"tight chest"],
    "shortness of breath": [r"short(?:ness)? of breath", r"can'?t breathe", r"cannot breathe", r"trouble breathing",
                            r"difficulty breathing", r"hard to breathe", r"breathless", r"struggling to breathe"],
    "palpitations": [r"palpitations?", r"heart (?:is )?(?:racing|pounding)", r"irregular heart ?beat"],
    "fainting": [r"fainted", r"fainting", r"passed out", r"black(?:ed)? out", r"syncope", r"lost consciousness"],
    "seizure": [r"seizures?", r"convulsions?"],
    "facial swelling": [r"swollen (?:face|lips?|tongue|throat)", r"(?:face|lips?|tongue|throat) (?:is |are )?swell(?:ing|ed)",
                        r"throat (?:is )?closing", r"anaphyla\w*"],
    "confusion": [r"confus(?:ed|ion)", r"disoriented"],
    "one-sided weakness": [r"one side of (?:my|the) (?:face|body)", r"face (?:is )?drooping", r"slurred speech",
                           r"can'?t (?:move|feel) (?:my )?(?:arm|leg)"],
    "coughing blood": [r"cough(?:ing)? (?:up )?blood", r"blood when i cough"],
    "self-harm thoughts": [r"suicid\w*", r"kill myself", r"end my life", r"hurt myself"],
}

# "no chest pain" / "without fainting" is negated; "no fever but chest pain" is not (but/and end the negation).
_NEGATION = re.compile(r"\b(?:no|not|never|without|don'?t have|didn'?t have|haven'?t had|no longer)\b"
                       r"(?:(?!\b(?:but|and|now)\b)[\w\s,']){0,15}$")
_COMPILED = {term: [re.compile(rf"(?<!\w){p}", re.I) for p in pats] for term, pats in RED_FLAGS.items()}


def flag_for(term: str | None, span: str | None) -> str | None:
    """The red-flag term an extracted symptom matches, or None."""
    t, span = (term or "").lower().replace("\u2019", "'"), (span or "").replace("\u2019", "'")
    if t in RED_FLAGS:
        return t
    for flag, pats in _COMPILED.items():
        if any(p.search(span) or p.search(t) for p in pats):
            return flag
    return None


def scan_text(text: str) -> list[tuple[str, str]]:
    """(red-flag term, verbatim span) found in the raw text, skipping simple negations ("no chest pain")."""
    found, norm = [], text.replace("\u2019", "'")  # same length, so offsets map back to the verbatim text
    for flag, pats in _COMPILED.items():
        for p in pats:
            m = next((m for m in p.finditer(norm) if not _NEGATION.search(norm[:m.start()].lower())), None)
            if m:
                found.append((flag, text[m.start():m.end()]))
                break
    return found
