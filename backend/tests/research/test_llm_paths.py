"""LLM paths with a fake LLM: whatever the model says, the deterministic checks decide."""
import pytest

from app.research import ask, concepts, deps, establish, graph


@pytest.fixture()
def fake_llm(monkeypatch):
    monkeypatch.setattr(deps, "llm_provider", lambda: "anthropic")
    replies = {}

    def call(purpose, prompt_file, variables, output_model, effort="low"):
        meta = dict(model="fake-model", prompt_hash=deps.prompt_hash(prompt_file), ok=True)
        reply = replies.get(purpose)
        if callable(reply):
            reply = reply(variables)
        if reply is None:
            return None, dict(meta, ok=False, stop_reason="refusal")
        return output_model.model_validate(reply), meta

    monkeypatch.setattr(deps, "llm_call", call)
    return replies


def test_llm_text_to_sql_runs_through_guard(db, fake_llm):
    fake_llm["ask_sql"] = dict(sql="SELECT sex, COUNT(DISTINCT pseudo_id) AS n_patients FROM pool.patients GROUP BY sex",
                               rationale="patients by sex")
    fake_llm["ask_summary"] = lambda v: dict(sentences=[
        dict(text=f"There are {v['rows'][0][1]} patients of sex {v['rows'][0][0]}.",
             cells=[dict(row=0, column="n_patients"), dict(row=0, column="sex")]),
        dict(text="Being female causes 999 visits.", cells=[dict(row=0, column="sex")])])
    r = ask.ask("How are patients split by sex in the pool?")
    assert r["mode"] == "llm" and r["guard"]["ok"]
    assert [s["status"] for s in r["summary"]] == ["verified", "needs_review"]
    assert any("causal" in x for x in r["summary"][1]["reasons"])


def test_llm_unsafe_sql_is_blocked(db, fake_llm):
    fake_llm["ask_sql"] = dict(sql="SELECT display_name, birth_date FROM curated.patients", rationale="names")
    r = ask.ask("Which patients had tinnitus?")
    assert not r["guard"]["ok"] and r["rows"] == [] and r["sufficiency"]["verdict"] == "NOT_SUPPORTED"


def test_llm_refusal_is_blocked_not_silent(db, fake_llm):
    fake_llm["ask_sql"] = None
    r = ask.ask("Which patients had tinnitus?")
    assert not r["guard"]["ok"] and "did not return SQL" in r["guard"]["violations"][0]


def test_llm_summary_failure_goes_to_review(db, fake_llm):
    fake_llm["ask_sql"] = dict(sql="SELECT sex, COUNT(*) AS n_patients FROM pool.patients GROUP BY sex", rationale="")
    fake_llm["ask_summary"] = None
    r = ask.ask("How are patients split by sex in the pool?")
    assert r["rows"] and r["summary"][0]["status"] == "needs_review"


def test_llm_establisher_output_is_checked(db, fake_llm):
    def reply(v):
        rels = []
        if "registry" in v["title"]:  # verbatim and correct → ACCEPTED
            rels.append(dict(subject="Moderna", relation="NO_ASSOCIATION_WITH", object="hypertension",
                             quote="Moderna vaccination was not associated with new hypertension diagnoses within 90 days."))
        if "cohort" in v["title"]:
            rels.append(dict(subject="mRNA-1273", relation="INCREASES_RISK_OF", object="hypertension",
                             quote="Hypertension onset was more frequent in adults over 40 after mRNA-1273 vaccination "
                                   "than in unvaccinated controls."))
        if "BNT162b2" in v["title"]:  # paraphrased quote → REJECTED
            rels.append(dict(subject="BNT162b2", relation="ADVERSE_EVENT_OF", object="myocarditis",
                             quote="BNT162b2 often causes myocarditis."))
        return dict(relations=rels)

    fake_llm["kg_establish"] = reply
    r = graph.build("covid_vaccine_safety", max_papers=3)
    assert (r["accepted"], r["rejected"]) == (2, 1)
    rows = deps.get_db().query("SELECT relation, status, lit_status FROM research.edges WHERE run_id = ?", [r["run_id"]])
    hyp = [x for x in rows if x["relation"] in ("INCREASES_RISK_OF", "NO_ASSOCIATION_WITH")]
    assert len(hyp) == 2 and all(x["status"] == "ACCEPTED" and x["lit_status"] == "CONTESTED" for x in hyp)
    assert [x["status"] for x in rows if x["relation"] == "ADVERSE_EVENT_OF"] == ["REJECTED"]
    lineage = deps.lineage_chain(next(e["edge_id"] for e in graph.get_graph("CVX:207")["edges"]
                                      if e["relation"] != "CITES"))
    assert any(x["agent"] == "establisher" and x["model"] == "fake-model" for x in lineage)


def test_establisher_llm_failure_gives_no_edges(db, fake_llm):
    fake_llm["kg_establish"] = None
    cands, meta = establish.establish(dict(title="t", abstract_text="x"), concepts.load_index(db))
    assert cands == [] and not meta["ok"]
