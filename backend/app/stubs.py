"""Contract-shaped example responses for endpoints that aren't built yet (M0).

Responses built from here carry the header `X-TrustLens-Stub: true`. Each owner replaces their stub when the
real implementation lands; the shapes here double as fixtures for the UI later.
"""
from __future__ import annotations

from . import models as m

PATIENT_ID = "b2f6e1c4-0000-4000-8000-000000000001"
_FACT = m.Fact(
    fact_id="FCT-STUB-0001", kind="LAB_TREND",
    data={"loinc": "2339-0", "name": "Glucose", "plain_name": "blood sugar", "units": "mg/dL",
          "latest": {"value": 91, "date": "2025-10-02", "flag": "NORMAL"},
          "previous": {"value": 142, "date": "2025-03-11", "flag": "HIGH"}, "direction": "down"},
    source_row_ids=["OBS-0004411", "OBS-0005120"],
)
_PASS = m.CriticResult(status="PASS")
_SUPPORTED = m.VerifierResult(status="SUPPORTED", reason="Both values and dates match the cited fact.")


def patients() -> list[m.PatientListItem]:
    return [m.PatientListItem(patient_id=PATIENT_ID, display_name="Synthetic Patient", age=57, sex="F",
                              last_encounter="2026-05-02")]


def facts(patient_id: str) -> m.PatientFacts:
    return m.PatientFacts(patient_id=patient_id, facts=[_FACT])


def summary(patient_id: str, audience: str, inject_error: bool) -> m.Summary:
    if audience == "patient":
        title = "Your lab results"
        text = "Your blood sugar was 142 mg/dL in March 2025, above the usual range. In October 2025 it was 91 mg/dL, in the usual range."
    else:
        title = "Labs (LOINC)"
        text = "Glucose (LOINC 2339-0) fell from 142 mg/dL (2025-03-11, high) to 91 mg/dL (2025-10-02, normal)."
    sentence = m.Sentence(sentence_id="SEN-STUB-0001", text=text, fact_ids=[_FACT.fact_id], status="verified",
                          critic=_PASS, verifier=_SUPPORTED)
    overall = "verified"
    if inject_error:
        sentence.text = text.replace("142", "159")
        sentence.critic = m.CriticResult(status="FLAG", reasons=["number 159 not found in cited facts"])
        sentence.verifier = m.VerifierResult(status="UNSUPPORTED", reason="159 does not match the cited fact.")
        sentence.status = "hidden_pending_review" if audience == "patient" else "needs_review"
        overall = "needs_review"
    return m.Summary(summary_id="SUM-STUB-0001", patient_id=patient_id, audience=audience, overall_status=overall,
                     sections=[m.Section(title=title, sentences=[sentence])], facts=[_FACT],
                     model="stub", prompt_hash="0" * 64, audit_seq=0)


def report(patient_id: str) -> m.ReportOut:
    imm = m.Evidence(kind="row", id="IMM-0000812")
    return m.ReportOut(report_id="RPT-STUB-0001", patient_id=patient_id, audit_seq=0, symptoms=[
        m.Symptom(symptom_id="SYM-STUB-0001", span="tired", term="fatigue", snomed_code="84229001",
                  classification="EXPECTED",
                  reason="Listed side effect of Moderna (CVX 207); dose 2026-10-28 is within the 14-day window",
                  evidence=[m.Evidence(kind="known_effect", id="KE-207-fatigue", source_url=None), imm],
                  review_status="not_required"),
        m.Symptom(symptom_id="SYM-STUB-0002", span="blurred vision", term="blurred vision", snomed_code=None,
                  classification="NEW", reason="Not a listed effect of Moderna (CVX 207) and not in the patient's record",
                  evidence=[imm], review_status="pending"),
    ])


def review_queue() -> m.ReviewQueue:
    return m.ReviewQueue(items=[m.ReviewItem(
        item_id="SYM-STUB-0002", kind="symptom", patient_id=PATIENT_ID, text="blurred vision",
        reason="NEW: not a listed side effect and not in the record", evidence=[{"kind": "row", "id": "IMM-0000812"}],
        created_at="2026-11-13T10:00:00+00:00")])


def rare() -> m.RareCases:
    return m.RareCases(items=[m.RareCase(term="blurred vision", exposure_label="Moderna (CVX 207)", age_band="40-49",
                                         sex="F", n_reports="<5", first_month="2026-11")])


def ask(question: str) -> m.AskOut:
    return m.AskOut(
        ask_id="ASK-STUB-0001", question=question,
        sql="SELECT age_band, COUNT(*) AS n_exposed FROM pool.immunizations WHERE concept_code = '207' GROUP BY age_band",
        guard=m.Guard(ok=True), columns=["age_band", "n_exposed", "n_hypertension", "rate_pct"],
        rows=[["40-49", "212", "19", "9.0"], ["30-39", "180", "<5", ""]], suppressed_cells=2,
        sufficiency=m.Sufficiency(verdict="CONDITIONAL", n=392,
                                  notes=["Association only, not causation", "2 cells under k=5 suppressed",
                                         "Planted synthetic signal (stub data)"]),
        summary=[m.AskSentence(text="Among vaccinated patients aged 40-49, 9.0% had a hypertension onset within 90 days (19 of 212).",
                               cells=[(0, "rate_pct"), (0, "n_hypertension"), (0, "n_exposed")], status="verified")],
        mode="template", audit_seq=0)


def graph_build() -> m.GraphBuildOut:
    return m.GraphBuildOut(run_id="KG-STUB-0001", papers=0, candidate_edges=0, accepted=0, rejected=0, audit_seq=0)


_EDGE = m.GraphEdge(
    edge_id="EDG-STUB-0001", src="CVX:207", dst="SNOMED:59621000", relation="ASSOCIATED_WITH",
    quote="(stub) exact sentence from the abstract", status="ACCEPTED", critic=_PASS,
    paper=m.PaperRef(paper_id="PMID:00000000", doi=None, title="(stub) paper title", year=2023,
                     url="https://europepmc.org/article/MED/00000000"),
    sanity=m.Sanity(literature="SINGLE_SOURCE", support_count=0, contradict_count=0, pool="UNTESTABLE"),
)


def graph() -> m.Graph:
    return m.Graph(
        nodes=[m.GraphNode(node_id="CVX:207", type="concept", label="SARS-COV-2 mRNA vaccine (Moderna)", code_system="CVX"),
               m.GraphNode(node_id="SNOMED:59621000", type="concept", label="Essential hypertension", code_system="SNOMED"),
               m.GraphNode(node_id="PMID:00000000", type="paper", label="(stub) paper title", year=2023)],
        edges=[_EDGE])


def edge(edge_id: str) -> m.EdgeDetail:
    return m.EdgeDetail(**{**_EDGE.model_dump(), "edge_id": edge_id})


def evals() -> m.Evals:
    return m.Evals(metrics=[m.EvalMetric(name="injected_error_catch_rate", value=None)],
                   details=[{"note": "evals land in M5"}])
