"""All shared §7 routes. Live in M0: /health, /audit, /audit/verify, /lineage/{id}. The rest return stubs.

When a slice lands, move its routes into their own module (routes_clinical.py, routes_research.py, ...).
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Response

from . import audit, lineage, llm, stubs
from . import models as m
from .db import get_db, table_count

router = APIRouter()


def _stub(response: Response) -> None:
    response.headers["X-TrustLens-Stub"] = "true"


# ---------- system ----------
@router.get("/health", response_model=m.Health, tags=["system"])
def health():
    db = get_db()
    return m.Health(db=db.dialect, llm=llm.provider(), counts={
        "patients": table_count(db, "curated.patients"),
        "papers": table_count(db, "research.papers"),
        "audit_events": table_count(db, "gov.audit_events"),
    })


# ---------- clinical (Dev B, M1/M2) ----------
@router.get("/patients", response_model=list[m.PatientListItem], tags=["clinical"])
def list_patients(response: Response, limit: int = Query(20, ge=1, le=500), vaccinated: bool | None = None):
    _stub(response)
    return stubs.patients()[:limit]


@router.get("/patients/{patient_id}/facts", response_model=m.PatientFacts, tags=["clinical"])
def patient_facts(patient_id: str, response: Response):
    _stub(response)
    return stubs.facts(patient_id)


@router.get("/patients/{patient_id}/summary", response_model=m.Summary, tags=["clinical"])
def patient_summary(patient_id: str, response: Response,
                    audience: Literal["patient", "physician"] = "patient",
                    inject_error: bool = False, refresh: bool = False):
    _stub(response)
    return stubs.summary(patient_id, audience, inject_error)


@router.post("/patients/{patient_id}/reports", response_model=m.ReportOut, tags=["clinical"])
def submit_report(patient_id: str, body: m.ReportIn, response: Response):
    _stub(response)
    return stubs.report(patient_id)


# ---------- oversight (Dev B, M2) ----------
@router.get("/review/queue", response_model=m.ReviewQueue, tags=["oversight"])
def review_queue(response: Response):
    _stub(response)
    return stubs.review_queue()


@router.post("/review/{item_id}", response_model=m.ReviewDecisionOut, tags=["oversight"])
def review_decision(item_id: str, body: m.ReviewDecisionIn, response: Response):
    _stub(response)
    return m.ReviewDecisionOut(ok=True, audit_seq=0)


# ---------- research (Dev C, M3) ----------
@router.get("/pool/rare", response_model=m.RareCases, tags=["research"])
def pool_rare(response: Response):
    _stub(response)
    return stubs.rare()


@router.post("/research/ask", response_model=m.AskOut, tags=["research"])
def research_ask(body: m.AskIn, response: Response):
    _stub(response)
    return stubs.ask(body.question)


@router.post("/research/graph/build", response_model=m.GraphBuildOut, tags=["research"])
def graph_build(body: m.GraphBuildIn, response: Response):
    _stub(response)
    return stubs.graph_build()


@router.get("/research/graph", response_model=m.Graph, tags=["research"])
def research_graph(response: Response, concept: str | None = None, depth: int = Query(1, ge=1, le=3)):
    _stub(response)
    return stubs.graph()


@router.get("/research/edges/{edge_id}", response_model=m.EdgeDetail, tags=["research"])
def research_edge(edge_id: str, response: Response):
    _stub(response)
    return stubs.edge(edge_id)


# ---------- governance (live) ----------
@router.get("/lineage/{item_id}", response_model=m.Lineage, tags=["governance"])
def get_lineage(item_id: str):
    result = lineage.chain(item_id)
    if result["type"] is None:
        raise HTTPException(status_code=404, detail=f"No lineage recorded for {item_id}")
    return result


@router.get("/audit", response_model=list[m.AuditEvent], tags=["governance"])
def get_audit(limit: int = Query(100, ge=1, le=1000)):
    return audit.list_events(limit)


@router.get("/audit/verify", response_model=m.AuditVerify, tags=["governance"])
def verify_audit():
    return audit.verify()


@router.get("/evals/latest", response_model=m.Evals, tags=["governance"])
def evals_latest(response: Response):
    _stub(response)
    return stubs.evals()
