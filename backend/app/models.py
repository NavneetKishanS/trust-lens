"""Pydantic models = the exact JSON shapes of shared §7. Change them only together with 00-shared.md."""
from __future__ import annotations

from datetime import date
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# ---------- system ----------
class Health(BaseModel):
    status: Literal["ok"] = "ok"
    db: Literal["exasol", "duckdb"]
    llm: Literal["bedrock", "anthropic", "stub"]
    counts: dict[str, Optional[int]]


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


# ---------- clinical ----------
class PatientListItem(BaseModel):
    patient_id: str
    display_name: str
    age: Optional[int]
    sex: Optional[str]
    last_encounter: Optional[str]


class Fact(BaseModel):
    fact_id: str
    kind: Literal["LAB_TREND", "CONDITION", "MEDICATION", "IMMUNIZATION", "ENCOUNTER", "CAREPLAN", "ALLERGY", "NEXT_STEP"]
    data: dict[str, Any]
    source_row_ids: list[str]


class PatientFacts(BaseModel):
    patient_id: str
    facts: list[Fact]


class CriticResult(BaseModel):
    status: Literal["PASS", "FLAG"]
    reasons: list[str] = Field(default_factory=list)


class VerifierResult(BaseModel):
    status: Literal["SUPPORTED", "UNSUPPORTED", "UNSURE"]
    reason: str = ""


class Sentence(BaseModel):
    sentence_id: str
    text: str
    fact_ids: list[str]
    status: Literal["verified", "needs_review", "hidden_pending_review"]
    critic: CriticResult
    verifier: VerifierResult


class Section(BaseModel):
    title: str
    sentences: list[Sentence]


class Summary(BaseModel):
    summary_id: str
    patient_id: str
    audience: Literal["patient", "physician"]
    overall_status: Literal["verified", "needs_review"]
    sections: list[Section]
    facts: list[Fact]
    model: str
    prompt_hash: str
    audit_seq: int


class ReportIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    onset_date: Optional[date] = None


class Evidence(BaseModel):
    kind: Literal["row", "known_effect"]
    id: str
    source_url: Optional[str] = None


class Symptom(BaseModel):
    symptom_id: str
    span: str
    term: str
    snomed_code: Optional[str]
    classification: Literal["EXPECTED", "IN_RECORD", "NEW", "UNMAPPED"]
    reason: str
    evidence: list[Evidence]
    review_status: Literal["not_required", "pending", "approved", "rejected"]


class ReportOut(BaseModel):
    report_id: str
    patient_id: str
    symptoms: list[Symptom]
    audit_seq: int


# ---------- oversight ----------
class ReviewItem(BaseModel):
    item_id: str
    kind: Literal["symptom", "sentence"]
    patient_id: Optional[str]
    text: str
    reason: str
    evidence: list[dict[str, Any]]
    created_at: str


class ReviewQueue(BaseModel):
    items: list[ReviewItem]


class ReviewDecisionIn(BaseModel):
    decision: Literal["approve", "reject"]
    reviewer: str = Field(min_length=1)
    note: str = ""


class ReviewDecisionOut(BaseModel):
    ok: bool
    audit_seq: int


# ---------- research ----------
class RareCase(BaseModel):
    term: str
    exposure_label: str
    age_band: str
    sex: str
    n_reports: str  # "<5" under k-anonymity
    first_month: str


class RareCases(BaseModel):
    k: int = 5
    items: list[RareCase]


class AskIn(BaseModel):
    question: str = Field(min_length=3, max_length=1000)


class Guard(BaseModel):
    ok: bool
    violations: list[str] = Field(default_factory=list)


class Sufficiency(BaseModel):
    verdict: Literal["SUPPORTED", "CONDITIONAL", "NOT_SUPPORTED"]
    n: Optional[int]
    notes: list[str] = Field(default_factory=list)


class AskSentence(BaseModel):
    text: str
    cells: list[tuple[int, str]]
    status: Literal["verified", "needs_review"]


class AskOut(BaseModel):
    ask_id: str
    question: str
    sql: Optional[str]
    guard: Guard
    columns: list[str]
    rows: list[list[str]]
    suppressed_cells: int
    sufficiency: Sufficiency
    summary: list[AskSentence]
    mode: Literal["llm", "template"]
    audit_seq: int


class GraphBuildIn(BaseModel):
    topic: str = "covid_vaccine_safety"
    max_papers: int = Field(default=60, ge=1, le=500)


class GraphBuildOut(BaseModel):
    run_id: str
    papers: int
    candidate_edges: int
    accepted: int
    rejected: int
    audit_seq: int


class GraphNode(BaseModel):
    node_id: str
    type: Literal["concept", "paper"]
    label: str
    code_system: Optional[str] = None
    pool_patients: Optional[str] = None
    year: Optional[int] = None


class PaperRef(BaseModel):
    paper_id: str
    doi: Optional[str]
    title: str
    year: Optional[int]
    url: str


class Sanity(BaseModel):
    literature: Literal["CONSISTENT", "CONTESTED", "SINGLE_SOURCE"]
    support_count: int
    contradict_count: int
    pool: Literal["OBSERVED", "NOT_OBSERVED", "UNTESTABLE"]
    pool_evidence: Optional[dict[str, Any]] = None


class GraphEdge(BaseModel):
    edge_id: str
    src: str
    dst: str
    relation: str
    quote: Optional[str] = None
    paper: Optional[PaperRef] = None
    critic: Optional[CriticResult] = None
    sanity: Optional[Sanity] = None
    status: Optional[Literal["ACCEPTED", "REJECTED"]] = None


class Graph(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class LineageLink(BaseModel):
    id: str
    type: str
    transform: Optional[str] = None
    agent: Optional[str] = None
    model: Optional[str] = None
    prompt_hash: Optional[str] = None
    depth: int


class Producer(BaseModel):
    agent: Optional[str]
    model: Optional[str]
    prompt_hash: Optional[str]


class Lineage(BaseModel):
    id: str
    type: str
    chain: list[LineageLink]
    producer: Optional[Producer]


class EdgeDetail(GraphEdge):
    lineage: list[LineageLink] = Field(default_factory=list)


# ---------- governance ----------
class AuditEvent(BaseModel):
    seq: int
    event_ts: str
    actor: str
    action_type: str
    subject: str
    payload: dict[str, Any]
    prev_hash: str
    row_hash: str


class AuditVerify(BaseModel):
    valid: bool
    length: int
    broken_at: Optional[int]


class EvalMetric(BaseModel):
    name: str
    value: Optional[float]


class Evals(BaseModel):
    eval_id: Optional[str] = None
    created_at: Optional[str] = None
    metrics: list[EvalMetric]
    details: list[dict[str, Any]]
    audit_seq: Optional[int] = None
