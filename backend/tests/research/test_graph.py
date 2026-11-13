from fastapi.testclient import TestClient

from app.research import concepts, critic, deps, graph, sanity
from tests.research.conftest import PAPERS


def _cand(subject_id, object_id, relation, quote, subject_text=None, object_text=None, paper_id="PMID:1"):
    return dict(subject_id=subject_id, object_id=object_id, subject_text=subject_text, object_text=object_text,
                relation=relation, quote=quote, paper_id=paper_id)


def test_critic_rules(db):
    idx = concepts.load_index(db)
    abstract = PAPERS[1]["abstract"]
    quote = "Moderna vaccination was not associated with new hypertension diagnoses within 90 days."
    seen = set()
    assert critic.check(_cand("CVX:207", "SNOMED:59621000", "NO_ASSOCIATION_WITH", quote), abstract, idx, seen)[0] == "PASS"
    # duplicate from the same paper
    assert "duplicate" in critic.check(_cand("CVX:207", "SNOMED:59621000", "NO_ASSOCIATION_WITH", quote),
                                       abstract, idx, seen)[1][0]
    # positive relation with a negation cue
    st, reasons = critic.check(_cand("CVX:207", "SNOMED:59621000", "INCREASES_RISK_OF", quote), abstract, idx, set())
    assert st == "FAIL" and any("negation" in r for r in reasons)
    # PL5: fabricated quote
    st, reasons = critic.check(_cand("CVX:207", "SNOMED:59621000", "INCREASES_RISK_OF", graph.PL5_QUOTE),
                               abstract, idx, set())
    assert st == "FAIL" and any("verbatim" in r for r in reasons)
    # entity not in quote
    st, reasons = critic.check(_cand("CVX:208", "SNOMED:59621000", "NO_ASSOCIATION_WITH", quote), abstract, idx, set())
    assert st == "FAIL" and any("subject" in r for r in reasons)
    # unknown relation, same subject and object
    st, reasons = critic.check(_cand("CVX:207", "CVX:207", "CURES", quote), abstract, idx, set())
    assert any("vocabulary" in r for r in reasons) and any("same concept" in r for r in reasons)
    # whitespace and curly quotes are normalised
    assert critic.check(_cand("CVX:207", "SNOMED:59621000", "NO_ASSOCIATION_WITH", quote.replace(" ", "  ")),
                        abstract, idx, set())[0] == "PASS"


def test_literature_labels():
    edges = [dict(edge_id="E1", src_id="A", dst_id="B", relation="ASSOCIATED_WITH", paper_id="P1"),
             dict(edge_id="E2", src_id="A", dst_id="B", relation="INCREASES_RISK_OF", paper_id="P2"),
             dict(edge_id="E3", src_id="A", dst_id="B", relation="NO_ASSOCIATION_WITH", paper_id="P3"),
             dict(edge_id="E4", src_id="A", dst_id="C", relation="ASSOCIATED_WITH", paper_id="P1")]
    lab = sanity.literature(edges, {"P1": 2021, "P2": 2023, "P3": 2024})
    assert lab["E1"]["lit_status"] == "CONTESTED" and lab["E1"]["support_count"] == 1 and lab["E1"]["contradict_count"] == 1
    assert lab["E1"]["support_years"] == {"oldest": 2021, "newest": 2023}
    assert lab["E4"]["lit_status"] == "SINGLE_SOURCE"


def test_pool_check_sees_planted_signal(db):
    idx = concepts.load_index(db)
    status, ev = sanity.pool_check("CVX:207", "SNOMED:59621000", idx, db)
    assert status == "OBSERVED", ev
    assert float(ev["exposed_rate"]) > float(ev["baseline_rate"]) and ev["synthetic"] is True
    assert sanity.pool_check("CVX:207", "SNOMED:50920009", idx, db)[0] == "UNTESTABLE"  # myocarditis not in pool
    assert sanity.pool_check("SNOMED:50920009", "SNOMED:3238004", idx, db)[0] == "UNTESTABLE"


def test_build_and_read_graph(db):
    r = graph.build("covid_vaccine_safety", max_papers=10, inject_fabricated_quote=True)
    assert r["papers"] == 3 and r["accepted"] >= 3 and r["rejected"] >= 1
    edges = db.query("SELECT * FROM research.edges WHERE run_id = ?", [r["run_id"]])
    abstracts = {f"PMID:{p['pmid']}": p["abstract"] for p in PAPERS}
    for e in edges:
        if e["status"] == "ACCEPTED":
            assert e["quote"] in abstracts[e["paper_id"]]
    pl5 = [e for e in edges if e["quote"] == graph.PL5_QUOTE]
    assert len(pl5) == 1 and pl5[0]["status"] == "REJECTED"

    g = graph.get_graph("CVX:207")
    hyp = [e for e in g["edges"] if e.get("relation") != "CITES"
           and {e["src"], e["dst"]} == {"CVX:207", "SNOMED:59621000"}]
    assert len(hyp) == 2  # one positive (2021), one negative (2024) → contested
    assert all(e["sanity"]["literature"] == "CONTESTED" for e in hyp)
    assert all(e["sanity"]["pool"] == "OBSERVED" and e["sanity"]["pool_evidence"]["sql"] for e in hyp)
    assert all(e["paper"]["url"].startswith("https://europepmc.org/article/MED/") for e in hyp)
    assert any(e.get("relation") == "CITES" for e in g["edges"])
    assert all(e["edge_id"] != pl5[0]["edge_id"] for e in g["edges"])  # rejected hidden by default
    node = next(n for n in g["nodes"] if n["node_id"] == "CVX:207")
    assert node["type"] == "concept" and int(node["pool_patients"]) >= 5

    detail = graph.get_edge(hyp[0]["edge_id"])
    types = {x["type"] for x in detail["lineage"]}
    assert {"paper", "critic_result", "sql"} <= types
    assert deps.audit_verify()["valid"]
    actions = {a["action_type"] for a in db.query("SELECT action_type FROM gov.audit_events")}
    assert {"kg.built", "edge.accepted", "edge.rejected"} <= actions


def test_api_shapes(db):
    from app.main import app

    c = TestClient(app)
    assert c.get("/health").json()["counts"]["papers"] == 3
    b = c.post("/research/graph/build", json={"topic": "covid_vaccine_safety", "max_papers": 5}).json()
    assert set(b) == {"run_id", "papers", "candidate_edges", "accepted", "rejected", "audit_seq"}
    g = c.get("/research/graph", params={"concept": "CVX:207"}).json()
    e = next(x for x in g["edges"] if x["relation"] != "CITES")
    assert set(e) >= {"edge_id", "src", "dst", "relation", "quote", "paper", "critic", "sanity", "status"}
    assert c.get(f"/research/edges/{e['edge_id']}").json()["lineage"]
    assert c.get("/research/edges/EDG-nope").status_code == 404
    a = c.post("/research/ask", json={"question": "What is the average HbA1c by age band?"}).json()
    assert set(a) >= {"ask_id", "question", "sql", "guard", "columns", "rows", "suppressed_cells", "sufficiency",
                      "summary", "mode", "audit_seq"}
    assert c.post("/research/ask", json={"question": "  "}).json()["error"]["code"] == "empty_question"
    assert c.get("/pool/rare").json()["k"] == 5
    assert c.get("/audit/verify").json()["valid"]
