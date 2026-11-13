import pytest
from fastapi.testclient import TestClient

from app import audit, lineage, llm
from app.clinical import agents, critic, facts, summary
from app.devdata import P1, P2, P3, load
from app.main import app


@pytest.fixture()
def data(db):
    assert load(db)
    return db


def kinds(fs):
    return [f["kind"] for f in fs]


# ---------- facts ----------
def test_lab_trend_fact_cites_both_rows(data):
    fs = facts.compute(P1)
    glucose = next(f for f in fs if f["kind"] == "LAB_TREND" and f["data"]["loinc"] == "2339-0")
    assert glucose["data"]["previous"] == {"value": 142, "date": "2025-03-11", "flag": "HIGH"}
    assert glucose["data"]["latest"] == {"value": 91, "date": "2025-10-02", "flag": "NORMAL"}
    assert glucose["data"]["direction"] == "down"
    assert glucose["source_row_ids"] == ["OBS-0000002", "OBS-0000001"]
    assert lineage.chain(glucose["fact_id"])["chain"][0]["type"] == "curated.observations"


def test_fact_ids_are_stable_and_stored(data):
    a = [f["fact_id"] for f in facts.compute(P1)]
    b = [f["fact_id"] for f in facts.compute(P1)]
    assert a == b
    assert len(data.query("SELECT fact_id FROM clinical.facts WHERE patient_id = ?", [P1])) == len(a)


def test_next_steps_are_rule_based(data):
    steps = [f["data"]["text"] for f in facts.compute(P2) if f["kind"] == "NEXT_STEP"]
    assert "Talk to your care team about your blood pressure (top number) result from February 2026." in steps
    assert any("Lifestyle education regarding hypertension" in s for s in steps)


def test_unknown_patient(data):
    with pytest.raises(facts.PatientNotFound):
        facts.compute("nobody")


# ---------- critic ----------
FACT = {"FCT-1": {"fact_id": "FCT-1", "kind": "LAB_TREND", "data": {
    "loinc": "2339-0", "name": "Glucose", "plain_name": "blood sugar", "units": "mg/dL",
    "latest": {"value": 91, "date": "2025-10-02", "flag": "NORMAL"},
    "previous": {"value": 142, "date": "2025-03-11", "flag": "HIGH"}}}}


@pytest.mark.parametrize("text,audience,reason", [
    ("Your blood sugar was 159 mg/dL in March 2025.", "patient", "number 159"),
    ("Your blood sugar was 142 mg/dL in April 2025.", "patient", "month 2025-04"),
    ("Glucose was 91 mg/dL on 2025-10-03.", "physician", "date 2025-10-03"),
    ("Your blood sugar was 142 mg/dL, so you may have diabetes.", "patient", "banned phrase"),
    ("Your blood sugar was 142 mg/dL in March 2025, a sign of diabetes.", "patient", "medical term 'diabetes'"),
    ("Glucose 91 mg/dL; recommend repeat testing.", "physician", "banned phrase for physician: 'recommend'"),
])
def test_critic_flags(text, audience, reason):
    r = critic.check(text, ["FCT-1"], FACT, audience)
    assert r["status"] == "FLAG" and any(reason in x for x in r["reasons"]), r


def test_critic_passes_faithful_sentence():
    text = "Your blood sugar was 142 mg/dL in March 2025, above the usual range. In 2 October 2025 it was 91 mg/dL."
    assert critic.check(text, ["FCT-1"], FACT, "patient") == {"status": "PASS", "reasons": []}


def test_critic_flags_unknown_fact():
    r = critic.check("Your blood sugar was 91 mg/dL.", ["FCT-404"], FACT, "patient")
    assert r["status"] == "FLAG" and "unknown fact_id(s): FCT-404" in r["reasons"]


# ---------- summary pipeline ----------
@pytest.mark.parametrize("pid", [P1, P2, P3])
@pytest.mark.parametrize("audience", ["patient", "physician"])
def test_stub_summaries_pass_the_critic(data, pid, audience):
    s = summary.get_summary(pid, audience)
    sentences = [x for sec in s["sections"] for x in sec["sentences"]]
    assert sentences and s["overall_status"] == "verified", [x["critic"] for x in sentences]
    fact_ids = {f["fact_id"] for f in s["facts"]}
    assert all(set(x["fact_ids"]) <= fact_ids and x["fact_ids"] for x in sentences)


def test_patient_view_has_no_conditions_and_physician_has_codes(data):
    p = summary.get_summary(P2, "patient")
    d = summary.get_summary(P2, "physician")
    assert "CONDITION" not in kinds(p["facts"]) and "CONDITION" in kinds(d["facts"])
    physician_text = " ".join(x["text"] for sec in d["sections"] for x in sec["sentences"])
    assert "SNOMED 59621000" in physician_text and "RxNorm 314076" in physician_text
    assert [sec["title"] for sec in p["sections"]] == ["Your lab results", "Your visits and care plans",
                                                       "Medicines and vaccines", "Next steps"]


def test_sentence_lineage_reaches_source_rows(data):
    s = summary.get_summary(P1, "patient")
    sid = s["sections"][0]["sentences"][0]["sentence_id"]
    chain = lineage.chain(sid)
    assert chain["producer"]["agent"] == "generator"
    types = {c["type"] for c in chain["chain"]}
    assert {"fact", "curated.observations", "llm_call"} <= types


@pytest.mark.parametrize("run", range(10))
def test_inject_error_is_always_caught(data, run):
    s = summary.get_summary(P1, "physician", inject_error=True)
    flagged = [x for sec in s["sections"] for x in sec["sentences"] if x["status"] == "needs_review"]
    assert s["overall_status"] == "needs_review" and len(flagged) == 1
    assert any("not in cited facts" in r for r in flagged[0]["critic"]["reasons"])
    changed = audit.list_events(5)[1]["payload"]["inject_error"]
    assert changed["from"] == "142" and "LOINC 2339-0" in changed["sentence"]  # the value changed, not the code


def test_inject_error_hidden_from_patient_and_audited(data):
    s = summary.get_summary(P1, "patient", inject_error=True)
    hidden = [x for sec in s["sections"] for x in sec["sentences"] if x["status"] == "hidden_pending_review"]
    assert len(hidden) == 1 and hidden[0]["text"] == summary.PATIENT_PLACEHOLDER
    events = audit.list_events()
    assert events[0]["action_type"] == "sentence.flagged" and events[1]["action_type"] == "summary.generated"
    assert events[1]["payload"]["inject_error"]["from"] == "142"
    assert audit.verify()["valid"]


def test_cache_and_refresh(data):
    a = summary.get_summary(P1, "patient")
    assert summary.get_summary(P1, "patient")["summary_id"] == a["summary_id"]
    assert summary.get_summary(P1, "patient", refresh=True)["summary_id"] != a["summary_id"]
    summary.get_summary(P1, "patient", inject_error=True)
    assert summary.get_summary(P1, "patient")["overall_status"] == "verified"


def test_hallucinating_generator_is_caught(data, monkeypatch):
    def fake_generate(audience, fs):
        f = next(x for x in fs if x["kind"] == "LAB_TREND" and x["data"]["loinc"] == "2339-0")
        out = agents.GenOut(sections=[agents.GenSection(title="Your lab results", sentences=[
            agents.GenSentence(text="Your blood sugar was 142 mg/dL in March 2025, so you have diabetes.",
                               fact_ids=[f["fact_id"]]),
            agents.GenSentence(text="Your cholesterol was 250 mg/dL.", fact_ids=["FCT-made-up"]),
        ])])
        return llm.LLMResult(parsed=out, ok=True, meta={"model": "fake", "prompt_hash": "f" * 64})

    monkeypatch.setattr(agents, "generate", fake_generate)
    s = summary.get_summary(P1, "patient", refresh=True)
    statuses = [x["status"] for sec in s["sections"] for x in sec["sentences"]]
    assert statuses == ["hidden_pending_review", "hidden_pending_review"]


def test_llm_outage_falls_back_to_templates_and_flags(data, monkeypatch):
    monkeypatch.setattr(llm, "provider", lambda: "anthropic")

    def down(*a, **k):
        raise ConnectionError("no network")

    monkeypatch.setattr(llm, "_parse", down)
    s = summary.get_summary(P1, "physician", refresh=True)
    assert s["model"] == "template-fallback" and s["overall_status"] == "needs_review"
    sentences = [x for sec in s["sections"] for x in sec["sentences"]]
    assert all(x["verifier"]["status"] == "UNSURE" for x in sentences)
    assert audit.list_events(50)[-1]["payload"]["generator_error"].startswith("ConnectionError")


# ---------- API ----------
@pytest.fixture()
def client(data):
    with TestClient(app) as c:
        yield c


def test_patient_routes_live(client):
    r = client.get("/patients")
    assert r.status_code == 200 and "X-TrustLens-Stub" not in r.headers
    assert {p["patient_id"] for p in r.json()} == {P1, P2, P3}
    assert [p["patient_id"] for p in client.get("/patients?vaccinated=true").json()] == [P1]
    assert client.get(f"/patients/{P1}/facts").json()["facts"]
    body = client.get(f"/patients/{P1}/summary?audience=physician&inject_error=true").json()
    assert body["overall_status"] == "needs_review"
    sid = body["sections"][0]["sentences"][0]["sentence_id"]
    assert client.get(f"/lineage/{sid}").json()["producer"]["agent"] == "generator"
    assert client.get("/audit/verify").json()["valid"]


def test_unknown_patient_404(client):
    r = client.get("/patients/nobody/summary")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
