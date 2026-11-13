"""Research routes (shared §7, Dev C): /pool/rare, /research/ask, /research/graph/build, /research/graph,
/research/edges/{edge_id}. Dev B's main.py includes this router: `app.include_router(research.router)`."""
from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.research import ask as ask_mod
from app.research import graph, papers

router = APIRouter(tags=["research"])


def error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


class AskRequest(BaseModel):
    question: str = Field(..., examples=["Is hypertension onset more common after the Moderna vaccine in patients over 40?"])
    sql: str | None = Field(None, description="Optional researcher-written SQL; goes through the same guard")


class BuildRequest(BaseModel):
    topic: str = "covid_vaccine_safety"
    max_papers: int = Field(60, ge=1, le=500)
    inject_fabricated_quote: bool = Field(False, description="PL5: plant one fabricated quote; A2 must reject it")


@router.get("/pool/rare")
def pool_rare():
    return ask_mod.get_rare()


@router.post("/research/ask")
def research_ask(body: AskRequest):
    if not body.question.strip() and not (body.sql or "").strip():
        return error(422, "empty_question", "question is empty")
    return ask_mod.ask(body.question, body.sql)


@router.get("/research/ask/templates")
def research_ask_templates():
    """The demo questions that work in stub mode (template path)."""
    return {"templates": [{"key": t.key, "question": t.example} for t in ask_mod.TEMPLATES]}


@router.post("/research/graph/build")
def research_graph_build(body: BuildRequest):
    if body.topic not in papers.TOPICS:
        return error(422, "unknown_topic", f"topic must be one of {sorted(papers.TOPICS)}")
    result = graph.build(body.topic, body.max_papers, body.inject_fabricated_quote)
    if result["papers"] == 0:
        return error(409, "no_papers", "no papers for this topic; run `python -m app.research.papers` first")
    return result


@router.get("/research/graph")
def research_graph(concept: str | None = Query(None, examples=["CVX:207"]), depth: int = Query(1, ge=1, le=3),
                   include_rejected: bool = False):
    return graph.get_graph(concept, depth, include_rejected)


@router.get("/research/edges/{edge_id}")
def research_edge(edge_id: str):
    edge = graph.get_edge(edge_id)
    if edge is None:
        return error(404, "not_found", f"edge {edge_id} not found")
    return edge
