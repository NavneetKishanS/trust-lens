from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import audit, lineage, llm
from app.clinical import review, summary, symptoms
from app.devdata import P1, P2, load
from app.main import app
from app.research import pool

DOSE = date(2026, 10, 28)  # P1's Moderna dose in the dev fixture


@pytest.fixture()
def data(db):
    assert load(db)
    return db


def by_term(report):
    return {s["term"]: s for s in report["symptoms"]}


def test_m2_exit_path(data):
    r = symptoms.submit_report(P1, "Since my booster I'm tired, have a headache and blurred vision.", date(2026, 10, 30))
    s = by_term(r)
    assert set(s) == {"fatigue", "headache", "blurred vision"}
    assert s["fatigue"]["classification"] == "EXPECTED" and s["fatigue"]["review_status"] == "not_required"
    assert s["headache"]["classification"] == "EXPECTED"
    assert "2 day(s) before onset" in s["fatigue"]["reason"]
    assert {"kind": "row", "id": "IMM-0000001"} in s["fatigue"]["evidence"]
    bv = s["blurred vision"]
    assert bv["classification"] == "NEW" and bv["review_status"] == "pending" and bv["snomed_code"] == "111516008"
    assert "Not a listed side effect of Moderna (CVX 207)" in bv["reason"]

    queue = review.queue()
    assert [i["item_id"] for i in queue] == [bv["symptom_id"]]
    assert pool.rare_cases()["items"] == []

    review.decide(bv["symptom_id"], "approve", "Dr. Weber", "plausible, keep for research")
    assert review.queue() == []
    assert pool.rare_cases() == {"k": 5, "items": [{
        "term": "blurred vision", "exposure_label": "Moderna (CVX 207)", "age_band": "50-59", "sex": "F",
        "n_reports": "<5", "first_month": "2026-10"}]}
    actions = [e["action_type"] for e in audit.list_events()]
    assert actions[:3] == ["review.decision", "symptom.flagged", "report.submitted"]
    assert audit.verify()["valid"]


def test_knee_pain_is_a_listed_moderna_effect(data):
    s = by_term(symptoms.submit_report(P1, "my knee hurts", date(2026, 11, 1)))
    assert s["joint pain"]["classification"] == "EXPECTED" and s["joint pain"]["span"] == "knee hurts"


def test_outside_window_is_new(data):
    s = by_term(symptoms.submit_report(P1, "I feel tired all the time", date(2026, 12, 30)))
    assert s["fatigue"]["classification"] == "NEW"
    assert data.query("SELECT exposure_code FROM community.symptoms")[0]["exposure_code"] == "207"


def test_symptom_in_record(data):
    s = by_term(symptoms.submit_report(P2, "My blood pressure is high again", date(2026, 3, 1)))
    hb = s["high blood pressure"]
    assert hb["classification"] == "IN_RECORD" and [e["id"] for e in hb["evidence"]] == ["CON-0000002"]
    assert "Essential hypertension" in hb["reason"]


def test_duplicates_merge_and_spans_are_verbatim(data):
    r = symptoms.submit_report(P1, "Tired, so EXHAUSTED.", date(2026, 10, 29))
    assert [(s["term"], s["span"]) for s in r["symptoms"]] == [("fatigue", "Tired")]


def test_llm_spans_are_verified_and_unknown_terms_unmapped(data, monkeypatch):
    def fake_call(purpose, prompt_file, variables, output_model, stub, **kw):
        return llm.LLMResult(parsed=symptoms.ExtractOut(symptoms=[
            symptoms.ExtractItem(span="weird metallic taste", term="metallic taste"),
            symptoms.ExtractItem(span="chest pain", term="chest pain"),  # not in the text: must be dropped
        ]), ok=True, meta={"model": "fake", "prompt_hash": "f" * 64})

    monkeypatch.setattr(llm, "call", fake_call)
    r = symptoms.submit_report(P1, "I have a weird metallic taste", date(2026, 10, 30))
    assert [(s["term"], s["classification"], s["review_status"]) for s in r["symptoms"]] == [
        ("metallic taste", "UNMAPPED", "pending")]


def test_extractor_outage_falls_back_to_keywords(data, monkeypatch):
    monkeypatch.setattr(llm, "provider", lambda: "anthropic")
    monkeypatch.setattr(llm, "_parse", lambda *a, **k: (_ for _ in ()).throw(TimeoutError("slow")))
    r = symptoms.submit_report(P1, "headache", date(2026, 10, 29))
    assert r["symptoms"][0]["classification"] == "EXPECTED"
    assert audit.list_events(3)[0]["payload"]["extractor_fallback"] == "keyword"


def test_symptom_lineage(data):
    r = symptoms.submit_report(P1, "headache", date(2026, 10, 29))
    chain = lineage.chain(r["symptoms"][0]["symptom_id"])
    assert {c["type"] for c in chain["chain"]} >= {"report", "ref.known_effects", "curated.immunizations"}


def test_review_rules(data):
    r = symptoms.submit_report(P1, "blurred vision", date(2026, 10, 30))
    sid = r["symptoms"][0]["symptom_id"]
    review.decide(sid, "reject", "Dr. Weber", "unrelated")
    with pytest.raises(review.AlreadyDecided):
        review.decide(sid, "approve", "Dr. Weber")
    with pytest.raises(review.ItemNotFound):
        review.decide("SYM-nope", "approve", "Dr. Weber")
    assert pool.rare_cases()["items"] == []


def test_flagged_sentence_review(data):
    s = summary.get_summary(P1, "patient", inject_error=True)
    item = next(i for i in review.queue() if i["kind"] == "sentence")
    assert "critic: number" in item["reason"] and item["patient_id"] == P1
    review.decide(item["item_id"], "reject", "Dr. Weber", "wrong value")
    reloaded = summary.load_summary(s["summary_id"], data)
    assert reloaded["overall_status"] == "verified"
    assert item["item_id"] not in {x["sentence_id"] for sec in reloaded["sections"] for x in sec["sentences"]}


# ---------- API ----------
@pytest.fixture()
def client(data):
    with TestClient(app) as c:
        yield c


def test_api_exit_path(client):
    r = client.post(f"/patients/{P1}/reports", json={"text": "tired, headache and blurred vision", "onset_date": "2026-10-30"})
    assert r.status_code == 200 and "X-TrustLens-Stub" not in r.headers
    pending = [s for s in r.json()["symptoms"] if s["review_status"] == "pending"]
    assert [s["term"] for s in pending] == ["blurred vision"]
    q = client.get("/review/queue").json()["items"]
    assert q[0]["item_id"] == pending[0]["symptom_id"]
    d = client.post(f"/review/{pending[0]['symptom_id']}", json={"decision": "approve", "reviewer": "Dr. Weber"})
    assert d.status_code == 200 and d.json()["ok"]
    again = client.post(f"/review/{pending[0]['symptom_id']}", json={"decision": "approve", "reviewer": "Dr. Weber"})
    assert again.status_code == 409 and again.json()["error"]["code"] == "conflict"
    assert client.get("/pool/rare").json()["items"][0]["term"] == "blurred vision"
    assert client.get("/audit/verify").json()["valid"]


def test_api_errors(client):
    assert client.post("/patients/nobody/reports", json={"text": "tired"}).status_code == 404
    assert client.post(f"/patients/{P1}/reports", json={"text": "tired", "onset_date": "yesterday"}).status_code == 422
    assert client.post("/review/XYZ-1", json={"decision": "approve", "reviewer": "x"}).status_code == 404
