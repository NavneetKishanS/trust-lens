"""A2 Critic: deterministic checks on every candidate edge from the A1 establisher (Dev C §4).

FAIL if any of:
- the quote is not a verbatim substring of the abstract (after normalising whitespace and quotes)
- subject or object (or one of their synonyms) does not appear in the quote
- NO_ASSOCIATION_WITH without a negation cue in the quote, or a positive relation with one
- relation not in the vocabulary, or subject == object
- duplicate of an existing edge from the same paper
"""
from __future__ import annotations

import re

from app.research.concepts import ConceptIndex

RELATIONS = {"ASSOCIATED_WITH", "INCREASES_RISK_OF", "DECREASES_RISK_OF", "ADVERSE_EVENT_OF", "TREATS",
             "NO_ASSOCIATION_WITH"}
NEGATIVE = "NO_ASSOCIATION_WITH"
_NEGATION = re.compile(r"\b(no|not|neither|nor)\b|n't\b|\bdid not\b|\bwas not associated\b", re.I)
_QUOTES = str.maketrans({"‘": "'", "’": "'", "‚": "'", "′": "'", "“": '"', "”": '"', "„": '"', "″": '"'})


def norm_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").translate(_QUOTES)).strip()


def has_negation(text: str) -> bool:
    return bool(_NEGATION.search(text or ""))


def _mentions(quote_lower: str, terms: list[str]) -> bool:
    for t in terms:
        t = norm_text(t).lower()
        if t and re.search(r"(?<![\w-])" + re.escape(t) + r"(?![\w-])", quote_lower):
            return True
    return False


def check(cand: dict, abstract: str, index: ConceptIndex, seen_keys: set[tuple]) -> tuple[str, list[str]]:
    """cand: subject_id, object_id, subject_text, object_text, relation, quote, paper_id.
    Returns ("PASS"|"FAIL", reasons). Adds the edge key to seen_keys when it passes."""
    reasons: list[str] = []
    quote = norm_text(cand.get("quote", ""))
    relation = cand.get("relation", "")

    if not quote:
        reasons.append("empty quote")
    elif quote not in norm_text(abstract):
        reasons.append("quote is not a verbatim sentence from the abstract")

    if relation not in RELATIONS:
        reasons.append(f"relation {relation!r} not in vocabulary")
    if cand["subject_id"] == cand["object_id"]:
        reasons.append("subject and object are the same concept")

    ql = quote.lower()
    if quote:
        if not _mentions(ql, index.terms_for(cand["subject_id"], cand.get("subject_text"))):
            reasons.append(f"subject {cand.get('subject_text') or cand['subject_id']!r} not mentioned in quote")
        if not _mentions(ql, index.terms_for(cand["object_id"], cand.get("object_text"))):
            reasons.append(f"object {cand.get('object_text') or cand['object_id']!r} not mentioned in quote")
        neg = has_negation(quote)
        if relation == NEGATIVE and not neg:
            reasons.append("NO_ASSOCIATION_WITH but the quote has no negation cue")
        if relation in RELATIONS and relation != NEGATIVE and neg:
            reasons.append(f"{relation} but the quote contains a negation cue")

    key = (cand.get("paper_id"), cand["subject_id"], cand["object_id"], relation)
    if key in seen_keys:
        reasons.append("duplicate of an existing edge from the same paper")
    if reasons:
        return "FAIL", reasons
    seen_keys.add(key)
    return "PASS", []
