"""A1 Establisher: proposes candidate relations from one abstract (Dev C §4).

LLM mode: prompts/kg_establish.md, effort low, at most 5 relations with a verbatim quote each.
Stub mode: sentences that mention two known concepts become ASSOCIATED_WITH (or NO_ASSOCIATION_WITH when the
sentence is negated). Either way the A2 critic checks every candidate; nothing is trusted on the way in.
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from app.research import deps
from app.research.concepts import CLASS_MEMBERS, ConceptIndex
from app.research.critic import has_negation

PROMPT = "kg_establish.md"
COVID_19 = "SNOMED:840539006"
MAX_RELATIONS = 5

RelationName = Literal["ASSOCIATED_WITH", "INCREASES_RISK_OF", "DECREASES_RISK_OF", "ADVERSE_EVENT_OF", "TREATS",
                       "NO_ASSOCIATION_WITH"]


class Relation(BaseModel):
    subject: str
    relation: RelationName
    object: str
    quote: str = Field(description="One sentence copied verbatim from the abstract")


class Relations(BaseModel):
    relations: list[Relation]


_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Za-z0-9(\[])")
_ABBREV = re.compile(r"(\b(e\.g|i\.e|vs|et al|fig|approx|ca|no|dr|mr|ms|resp|incl|cf)\.|\b[A-Z]\.)$", re.I)


def sentences(text: str) -> list[str]:
    """Split an abstract into sentences; re-join fragments that ended on an abbreviation ("e.g.", "vs.")."""
    out: list[str] = []
    for part in _SENT_SPLIT.split(text or ""):
        part = part.strip()
        if not part:
            continue
        if out and _ABBREV.search(out[-1]):
            out[-1] = f"{out[-1]} {part}"
        else:
            out.append(part)
    return out


def _is_population_context(sentence: str, start: int) -> bool:
    """True when the outcome term describes who was studied ("patients with hypertension"), not a result."""
    return bool(_POPULATION.search(sentence[:start]))


_POPULATION = re.compile(
    r"(history of|patients? with|individuals? with|people with|persons? with|subjects? with|participants? with|"
    r"adults? with|children with|women with|men with|presence of|such as|comorbidit\w*|pre-existing|underlying|"
    r"living with|suffering from|affected by|treatment for|diagnosed with|chronic illness\w*)\W+(?:[\w-]+\W+){0,6}$",
    re.I)
_NULL_FINDING = re.compile(r"\b(no|not|did not|was not|were not)\s+(\w+\s+){0,2}(associat\w*|evidence|increased?|"
                          r"elevated|significant|higher|linked|related|difference|excess|risk|signal)", re.I)
_RELATION_CUE = re.compile(r"\b(after|following|associated|association|risks?|increase\w*|elevat\w*|reported|"
                           r"occurr\w*|develop\w*|induc\w*|incidence|onset|linked|complications?|adverse|"
                           r"reactions?|rise|events?)\b", re.I)


def stub_relations(abstract: str, index: ConceptIndex) -> list[dict]:
    """Deterministic stand-in for the LLM: an exposure and an outcome named in the same sentence, with a relation
    cue word ("after", "associated", "risk", …). Outcomes that only describe the study population ("patients with
    hypertension") and pairs of two exposures are skipped; each pair is proposed once per paper."""
    scored, seen = [], set()
    for pos, sent in enumerate(sentences(abstract)):
        if not _RELATION_CUE.search(sent):
            continue
        found, ids = [], set()
        for cid, text, start in index.find(sent):
            if cid not in ids:
                ids.add(cid)
                found.append((cid, text, start))
        exposures = [f[:2] for f in found if index.get(f[0]) and index.get(f[0]).is_exposure]
        if any(e[0] not in CLASS_MEMBERS for e in exposures):  # "Moderna COVID-19 vaccine": keep the product only
            exposures = [e for e in exposures if e[0] not in CLASS_MEMBERS]
        outcomes = [f[:2] for f in found if f[:2] not in exposures and f[0] not in CLASS_MEMBERS
                    and not _is_population_context(sent, f[2])]
        if exposures:  # "COVID-19" next to a COVID-19 vaccine is near-universal and says nothing on its own
            outcomes = [o for o in outcomes if o[0] != COVID_19]
        pairs = [(e, o, 0) for e in exposures for o in outcomes]
        if not exposures and len(outcomes) >= 2:
            pairs = [(outcomes[0], outcomes[1], 1)]
        if has_negation(sent):
            # only explicit null findings become NO_ASSOCIATION_WITH; other negated sentences are too ambiguous for a stub
            if not _NULL_FINDING.search(sent):
                continue
            relation = "NO_ASSOCIATION_WITH"
        else:
            relation = "ASSOCIATED_WITH"
        for subj, obj, prio in pairs:
            key = (subj[0], obj[0], relation)
            if key in seen:
                continue
            seen.add(key)
            # exposure → outcome first, then sentences near the end of the abstract (conclusions)
            scored.append((prio, -pos, dict(subject=subj[1], relation=relation, object=obj[1], quote=sent)))
    scored.sort(key=lambda x: (x[0], x[1]))
    return [s[2] for s in scored[:MAX_RELATIONS]]


def establish(paper: dict, index: ConceptIndex) -> tuple[list[dict], dict]:
    """Returns (candidates, meta). Candidates are dicts with subject, relation, object, quote."""
    if deps.llm_provider() == "stub":
        return stub_relations(paper["abstract_text"], index), dict(model="stub", prompt_hash=deps.prompt_hash(PROMPT),
                                                                   ok=True, agent_mode="stub")
    hints = sorted({t for c in index.by_id.values() for t in c.terms()[:2] if len(t) < 40})[:120]
    parsed, meta = deps.llm_call("kg_establish", PROMPT, dict(
        title=paper.get("title") or "", abstract=paper["abstract_text"], concept_hints=", ".join(hints)),
        Relations, effort="low")
    meta = dict(meta, agent_mode="llm")
    if parsed is None:
        return [], meta
    return [r.model_dump() for r in parsed.relations[:MAX_RELATIONS]], meta
