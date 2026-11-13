from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app import audit, lineage, llm
from app.main import app
from app.schema import ensure_gov_schema


# ---------- audit ----------
def test_audit_chain_appends_and_verifies(db):
    assert audit.verify() == {"valid": True, "length": 0, "broken_at": None}
    s1 = audit.append("dev-a", "data.loaded", "curated.patients", {"rows": 1000})
    s2 = audit.append("dr.weber", "review.decision", "SYM-1", {"decision": "approve"})
    assert (s1, s2) == (1, 2)
    events = audit.list_events()
    assert events[0]["seq"] == 2 and events[0]["prev_hash"] == events[1]["row_hash"]
    assert events[1]["prev_hash"] == audit.GENESIS
    assert audit.verify() == {"valid": True, "length": 2, "broken_at": None}


def test_audit_detects_tampering(db):
    for i in range(3):
        audit.append("system", "data.loaded", f"t{i}", {"i": i})
    db.execute("UPDATE gov.audit_events SET payload_json = '{\"i\":99}' WHERE seq = 2")
    assert audit.verify() == {"valid": False, "length": 3, "broken_at": 2}


def test_audit_detects_deleted_row(db):
    for i in range(3):
        audit.append("system", "data.loaded", f"t{i}", {"i": i})
    db.execute("DELETE FROM gov.audit_events WHERE seq = 2")
    assert audit.verify()["broken_at"] == 3


def test_audit_rejects_unknown_action(db):
    with pytest.raises(ValueError):
        audit.append("x", "made.up", "s")


def test_gov_schema_is_idempotent(db):
    ensure_gov_schema(db)
    ensure_gov_schema(db)


# ---------- lineage ----------
def test_lineage_chain_walks_upstream(db):
    lineage.add("SEN-1", "sentence", [("FCT-1", "fact")], transform="generator", agent="generator",
                model="stub", prompt_hash="a" * 64)
    lineage.add("FCT-1", "fact", [("OBS-1", "curated.observations"), ("OBS-2", "curated.observations")],
                transform="facts.sql:lab_trend")
    lineage.add("OBS-1", "curated.observations", [("file:observations.csv", "file")], transform="load:synthea")
    result = lineage.chain("SEN-1")
    assert result["type"] == "sentence"
    assert result["producer"] == {"agent": "generator", "model": "stub", "prompt_hash": "a" * 64}
    assert [(c["id"], c["depth"]) for c in result["chain"]] == [
        ("FCT-1", 1), ("OBS-1", 2), ("OBS-2", 2), ("file:observations.csv", 3)]


def test_lineage_unknown_id(db):
    assert lineage.chain("NOPE")["type"] is None


# ---------- llm ----------
class Out(BaseModel):
    answer: str


@pytest.fixture()
def prompt(tmp_path):
    p = tmp_path / "p.md"
    p.write_text("Answer about {{topic}} using {{facts}}")
    return p


def test_llm_stub_logs_call(db, prompt):
    r = llm.call("test", prompt, {"topic": "x", "facts": [{"b": 1, "a": 2}]}, Out, stub=lambda: Out(answer="hi"))
    assert r.ok and r.parsed.answer == "hi" and r.meta["model"] == "stub"
    assert r.meta["prompt_hash"] == llm.sha256(prompt.read_text())
    row = db.query("SELECT purpose, ok, prompt_hash FROM gov.llm_calls")[0]
    assert row["purpose"] == "test" and row["ok"] is True


def test_render_is_stable():
    t = "{{facts}}"
    assert llm.render(t, {"facts": {"b": 1, "a": 2}}) == '{"a": 2, "b": 1}'


def _fake_response(stop_reason, parsed=None):
    return SimpleNamespace(stop_reason=stop_reason, model="claude-opus-5-5", parsed_output=parsed,
                           stop_details=SimpleNamespace(category="bio") if stop_reason == "refusal" else None)


@pytest.mark.parametrize("stop_reason,parsed,ok,error", [
    ("end_turn", Out(answer="ok"), True, None),
    ("refusal", None, False, "refusal (bio)"),
    ("max_tokens", None, False, "output truncated at max_tokens"),
])
def test_llm_stop_reasons(db, prompt, monkeypatch, stop_reason, parsed, ok, error):
    monkeypatch.setattr(llm, "provider", lambda: "anthropic")
    monkeypatch.setattr(llm, "_parse", lambda *a, **k: _fake_response(stop_reason, parsed))
    r = llm.call("test", prompt, {}, Out, stub=lambda: Out(answer="stub"))
    assert r.ok is ok and r.meta["error"] == error
    assert (r.parsed is not None) is ok


def test_llm_exception_never_raises(db, prompt, monkeypatch):
    monkeypatch.setattr(llm, "provider", lambda: "anthropic")

    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(llm, "_parse", boom)
    r = llm.call("test", prompt, {}, Out, stub=lambda: Out(answer="stub"))
    assert not r.ok and "network down" in r.meta["error"]
    assert db.query("SELECT ok FROM gov.llm_calls")[0]["ok"] is False


# ---------- API ----------
@pytest.fixture()
def client(db):
    with TestClient(app) as c:
        yield c


def test_health(client):
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["db"] == "duckdb" and body["llm"] == "stub"
    assert body["counts"]["patients"] is None and body["counts"]["audit_events"] == 0


STUB_CALLS = [
    ("get", "/patients", None),
    ("get", "/patients/P1/facts", None),
    ("get", "/patients/P1/summary?audience=patient", None),
    ("get", "/patients/P1/summary?audience=physician&inject_error=true", None),
    ("post", "/patients/P1/reports", {"text": "tired and blurred vision"}),
    ("post", "/research/ask", {"question": "hypertension after Moderna by age band"}),
    ("post", "/research/graph/build", {"topic": "covid_vaccine_safety", "max_papers": 10}),
    ("get", "/research/graph?concept=CVX:207", None),
    ("get", "/research/edges/EDG-1", None),
    ("get", "/evals/latest", None),
]


@pytest.mark.parametrize("method,path,body", STUB_CALLS)
def test_stub_routes_return_contract_shapes(client, method, path, body):
    r = getattr(client, method)(path, json=body) if body else getattr(client, method)(path)
    assert r.status_code == 200, r.text
    assert r.headers["X-TrustLens-Stub"] == "true"


def test_inject_error_stub_is_flagged(client):
    s = client.get("/patients/P1/summary?audience=patient&inject_error=true").json()
    sent = s["sections"][0]["sentences"][0]
    assert s["overall_status"] == "needs_review" and sent["status"] == "hidden_pending_review"
    assert sent["critic"]["status"] == "FLAG"


def test_governance_routes_are_live(client):
    audit.append("system", "data.loaded", "curated.patients", {"rows": 3})
    lineage.add("FCT-9", "fact", [("OBS-9", "curated.observations")], transform="facts.sql:lab_trend")
    assert client.get("/audit").json()[0]["action_type"] == "data.loaded"
    assert client.get("/audit/verify").json() == {"valid": True, "length": 1, "broken_at": None}
    assert client.get("/lineage/FCT-9").json()["chain"][0]["id"] == "OBS-9"
    assert "X-TrustLens-Stub" not in client.get("/audit").headers


def test_error_shapes(client):
    r = client.get("/lineage/NOPE")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    r = client.post("/patients/P1/reports", json={"text": ""})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_request"
