"""Red-flag symptoms (shared §8): deterministic, forced to review, first in the queue, fixed patient advice."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import audit
from app.clinical import red_flags, review, symptoms
from app.devdata import P1, load
from app.main import app


@pytest.fixture()
def data(db):
    assert load(db)
    return db


@pytest.mark.parametrize("text,flag", [
    ("I have chest pain", "chest pain"),
    ("I can’t breathe properly", "shortness of breath"),
    ("yesterday I passed out in the kitchen", "fainting"),
    ("my lips are swelling", "facial swelling"),
    ("no fever but chest tightness", "chest pain"),
])
def test_scan_finds_red_flags(text, flag):
    found = red_flags.scan_text(text)
    assert flag in [f for f, _ in found]
    assert all(span in text for _, span in found)  # spans are verbatim, curly apostrophes included


@pytest.mark.parametrize("text", ["no chest pain, just tired", "I haven't had any shortness of breath", "headache and tired"])
def test_scan_skips_negations_and_ordinary_symptoms(text):
    assert red_flags.scan_text(text) == []


def test_urgent_report_forces_review_and_advice(data):
    r = symptoms.submit_report(P1, "Since my booster I'm tired and I have chest pain and can't breathe", date(2026, 10, 30))
    by = {s["term"]: s for s in r["symptoms"]}
    assert r["urgent"] and r["urgent_advice"] == red_flags.URGENT_ADVICE and "112" in r["urgent_advice"]
    assert not by["fatigue"]["urgent"] and by["fatigue"]["review_status"] == "not_required"
    urgent = [s for s in r["symptoms"] if s["urgent"]]
    assert {s["term"] for s in urgent} >= {"chest pain", "shortness of breath"}
    assert all(s["review_status"] == "pending" and s["reason"].startswith(red_flags.URGENT_PREFIX) for s in urgent)
    events = [e for e in audit.list_events(limit=50) if e["action_type"] == "symptom.flagged"]
    assert events and all(e["payload"]["urgent"] for e in events)


def test_ordinary_report_is_not_urgent(data):
    r = symptoms.submit_report(P1, "tired, headache and blurred vision", date(2026, 10, 30))
    assert not r["urgent"] and r["urgent_advice"] is None and not any(s["urgent"] for s in r["symptoms"])


def test_urgent_items_come_first_in_the_queue(data):
    symptoms.submit_report(P1, "I passed out yesterday", date(2026, 10, 30))
    symptoms.submit_report(P1, "blurred vision", date(2026, 10, 30))  # newer, but not urgent
    q = review.queue()
    assert q[0]["priority"] == "urgent" and q[-1]["priority"] == "normal"


def test_api_returns_urgent_fields(data):
    with TestClient(app) as c:
        r = c.post(f"/patients/{P1}/reports", json={"text": "chest pain", "onset_date": "2026-10-30"}).json()
        assert r["urgent"] and r["urgent_advice"] and r["symptoms"][0]["urgent"]
        assert c.get("/review/queue").json()["items"][0]["priority"] == "urgent"
        h = c.get("/health").json()
        assert h["llm"] == "stub" and h["llm_region"] is None and h["llm_eu_only"] is None and h["db_location"] == "local"
