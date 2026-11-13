"""Generator and verifier agents. Both go through llm.call, so stub mode, logging and failure handling are uniform."""
from __future__ import annotations

import re

from pydantic import BaseModel, Field

from .. import llm
from . import templates


# ---------- generator ----------
class GenSentence(BaseModel):
    text: str
    fact_ids: list[str]


class GenSection(BaseModel):
    title: str
    sentences: list[GenSentence]


class GenOut(BaseModel):
    sections: list[GenSection]


def _compact(facts: list[dict]) -> list[dict]:
    return [{"fact_id": f["fact_id"], "kind": f["kind"], "data": f["data"]} for f in facts]


def _stub_generate(audience: str, facts: list[dict]) -> GenOut:
    by_section: dict[str, list[GenSentence]] = {}
    for f in facts:
        title = templates.SECTIONS[audience][f["kind"]]
        by_section.setdefault(title, []).append(
            GenSentence(text=templates.stub_sentence(audience, f), fact_ids=[f["fact_id"]]))
    return GenOut(sections=[GenSection(title=t, sentences=by_section[t])
                            for t in templates.SECTION_ORDER[audience] if t in by_section])


def generate(audience: str, facts: list[dict]) -> llm.LLMResult[GenOut]:
    sections = [t for t in templates.SECTION_ORDER[audience]
                if any(templates.SECTIONS[audience][f["kind"]] == t for f in facts)]
    return llm.call(
        purpose=f"summary.generate.{audience}", prompt_file=f"summary_{audience}.md",
        variables={"sections": ", ".join(sections), "facts": _compact(facts)},
        output_model=GenOut, stub=lambda: _stub_generate(audience, facts), effort="medium",
    )


def inject_error(gen: GenOut, facts_by_id: dict[str, dict]) -> dict | None:
    """PL1: change one number in the first sentence that cites a lab fact. Returns what was changed."""
    from .critic import _extract_dates  # dates must stay intact so only the number check fires

    for section in gen.sections:
        for sentence in section.sentences:
            labs = [facts_by_id[f] for f in sentence.fact_ids if facts_by_id.get(f, {}).get("kind") == "LAB_TREND"]
            if not labs:
                continue
            values = {float(p["value"]) for lab in labs for p in (lab["data"]["latest"], lab["data"].get("previous")) if p}
            _, masked = _extract_dates(sentence.text)
            # change a measured value, never a code or the "1" in "HbA1c"
            m = next((m for m in re.finditer(r"(?<![\w.-])\d+(?:\.\d+)?(?![\w.-])", masked)
                      if float(m.group(0)) in values), None)
            if not m:
                continue
            old = m.group(0)
            new = str(int(float(old)) + 17) if "." not in old else f"{float(old) + 1.7:.1f}"
            sentence.text = sentence.text[:m.start()] + new + sentence.text[m.end():]
            return {"from": old, "to": new, "sentence": sentence.text}
    return None


# ---------- verifier ----------
class VerdictItem(BaseModel):
    index: int
    status: str = Field(description="SUPPORTED, UNSUPPORTED or UNSURE")
    reason: str


class VerifyOut(BaseModel):
    results: list[VerdictItem]


def verify(items: list[dict], critic_results: list[dict]) -> tuple[list[dict], dict]:
    """items: [{index, text, facts}]. Returns ([{status, reason}] aligned with items, llm meta)."""
    def stub():
        return VerifyOut(results=[
            VerdictItem(index=i["index"], status="SUPPORTED" if c["status"] == "PASS" else "UNSUPPORTED",
                        reason="Stub verifier: matches the critic result." if c["status"] == "PASS"
                        else "Stub verifier: " + "; ".join(c["reasons"]))
            for i, c in zip(items, critic_results)])

    if not items:
        return [], {}
    result = llm.call(purpose="summary.verify", prompt_file="verifier.md", variables={"sentences": items},
                      output_model=VerifyOut, stub=stub, effort="low")
    if not result.ok:
        reason = f"Verifier unavailable ({result.meta.get('error')}); needs a human check."
        return [{"status": "UNSURE", "reason": reason} for _ in items], result.meta
    by_index = {r.index: r for r in result.parsed.results}
    out = []
    for i in items:
        r = by_index.get(i["index"])
        status = r.status.upper() if r and r.status.upper() in {"SUPPORTED", "UNSUPPORTED", "UNSURE"} else "UNSURE"
        out.append({"status": status, "reason": r.reason if r else "Verifier returned no result for this sentence."})
    return out, result.meta
