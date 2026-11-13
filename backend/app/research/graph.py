"""Knowledge graph: build (A1 establish → A2 critic → A3 sanity) and read (Dev C §4, shared §7).

The graph lives in Exasol tables: research.edges, research.citations; nodes are ref.concepts + papers.
Each build is a new run; reads and literature counts use the latest run only, so rebuilding never double-counts.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from app.research import concepts as concepts_mod
from app.research import critic, deps, establish, papers, sanity, store

ACTOR = "research.graph"
# PL5 (shared §10): a fabricated quote planted on one candidate edge. A2 must reject it.
PL5_QUOTE = "mRNA-1273 vaccination tripled the risk of hypertension in every age group studied."


def _pick_papers(db, topic: str, max_papers: int) -> list[dict]:
    """Round-robin over the topic's queries, alternating newest and oldest within each query, so a small build
    still covers every query and mixes old and recent research."""
    queries = papers.TOPICS.get(topic)
    if not queries:
        raise ValueError(f"unknown topic {topic!r}")
    rows = db.query(
        f"SELECT * FROM research.papers WHERE query IN ({', '.join('?' for _ in queries)}) ORDER BY pub_year, paper_id",
        list(queries))
    queues = []
    for q in queries:
        qrows = [r for r in rows if r["query"] == q]
        order, lo, hi = [], 0, len(qrows) - 1
        while lo <= hi:
            order.append(qrows[hi]); hi -= 1
            if lo <= hi:
                order.append(qrows[lo]); lo += 1
        queues.append(order)
    picked = []
    while len(picked) < max_papers and any(queues):
        for qu in queues:
            if qu and len(picked) < max_papers:
                picked.append(qu.pop(0))
    return picked


def build(topic: str = "covid_vaccine_safety", max_papers: int = 60, inject_fabricated_quote: bool = False,
          db=None) -> dict:
    db = db or deps.get_db()
    store.ensure_schema(db)
    index = concepts_mod.load_index(db)
    run = store.run_id("KG")
    selected = _pick_papers(db, topic, max_papers)

    workers = 1 if deps.llm_provider() == "stub" else 6
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda p: (p, *establish.establish(p, index)), selected))

    created, rows, llm_failures, planted_id = store.now(), [], 0, None
    seen: set[tuple] = set()
    for i, (paper, cands, meta) in enumerate(results):
        if not meta.get("ok"):
            llm_failures += 1
        cands = [dict(c, planted=None) for c in cands]
        if inject_fabricated_quote and i == 0:
            cands.append(dict(subject="mRNA-1273", relation="INCREASES_RISK_OF", object="hypertension",
                              quote=PL5_QUOTE, planted="PL5"))
        for c in cands:
            cand = dict(subject_id=index.resolve(c["subject"]), object_id=index.resolve(c["object"]),
                        subject_text=c["subject"], object_text=c["object"], relation=c["relation"],
                        quote=critic.norm_text(c["quote"]), paper_id=paper["paper_id"])
            status, reasons = critic.check(cand, paper["abstract_text"], index, seen)
            edge_id = "EDG-" + store.short_hash(run, paper["paper_id"], cand["subject_id"], cand["object_id"],
                                                cand["relation"], cand["quote"], str(len(rows)))
            if c["planted"]:
                planted_id = edge_id
            rows.append(dict(
                edge_id=edge_id, run_id=run, src_id=cand["subject_id"], dst_id=cand["object_id"],
                relation=cand["relation"], quote=cand["quote"], paper_id=paper["paper_id"], critic_status=status,
                critic_reasons=store.dumps(reasons), lit_status=None, support_count=None, contradict_count=None,
                pool_status=None, pool_evidence_json=None,
                status="ACCEPTED" if status == "PASS" else "REJECTED", created_at=created,
                _meta=meta, _planted=c["planted"]))

    # A3 sanity on accepted edges
    accepted = [r for r in rows if r["status"] == "ACCEPTED"]
    years = {p["paper_id"]: p.get("pub_year") for p in selected}
    lit = sanity.literature(accepted, years)
    pool_cache: dict[frozenset, tuple] = {}
    for r in accepted:
        r.update({k: v for k, v in lit[r["edge_id"]].items() if k != "support_years"})
        pair = frozenset((r["src_id"], r["dst_id"]))
        if pair not in pool_cache:
            pool_cache[pair] = sanity.pool_check(r["src_id"], r["dst_id"], index, db)
        r["pool_status"], evidence = pool_cache[pair]
        r["pool_evidence_json"] = store.dumps(evidence) if evidence else None

    db.insert_rows("research.edges", [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows])

    for r in rows:
        meta = r["_meta"]
        deps.lineage_add(r["edge_id"], "kg_edge", [(r["paper_id"], "paper")], "kg:a1_establish",
                         agent="establisher", model=meta.get("model"), prompt_hash=meta.get("prompt_hash"))
        deps.lineage_add(r["edge_id"], "kg_edge", [(f"CRITIC:{r['edge_id']}", "critic_result")], "research/critic.py",
                         agent="critic")
        if r["pool_evidence_json"]:
            ev = store.loads(r["pool_evidence_json"], {})
            if ev.get("sql_hash"):
                deps.lineage_add(r["edge_id"], "kg_edge", [(f"SQL:{ev['sql_hash']}", "sql")], ev.get("sql_source"),
                                 agent="sanity")
        deps.audit_append(ACTOR, "edge.accepted" if r["status"] == "ACCEPTED" else "edge.rejected", r["edge_id"], dict(
            run_id=run, paper_id=r["paper_id"], relation=r["relation"], src=r["src_id"], dst=r["dst_id"],
            critic_reasons=store.loads(r["critic_reasons"], []), lit_status=r["lit_status"],
            pool_status=r["pool_status"], planted=r["_planted"]))

    n_acc = len(accepted)
    summary = dict(run_id=run, papers=len(selected), candidate_edges=len(rows), accepted=n_acc,
                   rejected=len(rows) - n_acc)
    payload = dict(summary, topic=topic, mode=deps.llm_provider(), llm_failures=llm_failures,
                   planted_pl5=planted_id,
                   pl5_status=next((r["status"] for r in rows if r["edge_id"] == planted_id), None))
    summary["audit_seq"] = deps.audit_append(ACTOR, "kg.built", run, payload)
    return summary


# ------------------------------------------------------------------------------------------- read


def latest_run(db) -> str | None:
    if not deps.table_exists(db, "research.edges"):
        return None
    r = db.query("SELECT MAX(run_id) AS run_id FROM research.edges")
    return r[0]["run_id"] if r else None


def _paper_map(db, ids: set[str]) -> dict[str, dict]:
    out, ids = {}, sorted(ids)
    for i in range(0, len(ids), 200):
        part = ids[i:i + 200]
        for p in db.query(f"SELECT paper_id, pmid, doi, title, journal, pub_year, source_url FROM research.papers "
                          f"WHERE paper_id IN ({', '.join('?' for _ in part)})", part):
            out[p["paper_id"]] = p
    return out


def edge_view(r: dict, paper: dict | None, support_years=None) -> dict:
    ev = store.loads(r.get("pool_evidence_json"), None)
    return dict(
        edge_id=r["edge_id"], src=r["src_id"], dst=r["dst_id"], relation=r["relation"], quote=r["quote"],
        paper=dict(paper_id=r["paper_id"], doi=(paper or {}).get("doi"), title=(paper or {}).get("title"),
                   year=(paper or {}).get("pub_year"),
                   url=(paper or {}).get("source_url") or f"https://europepmc.org/article/MED/{r['paper_id'][5:]}"),
        critic=dict(status=r["critic_status"], reasons=store.loads(r["critic_reasons"], [])),
        sanity=dict(literature=r.get("lit_status"), support_count=r.get("support_count"),
                    contradict_count=r.get("contradict_count"), support_years=support_years,
                    pool=r.get("pool_status"), pool_evidence=ev),
        status=r["status"])


def pool_patient_count(db, concept_id: str) -> str | None:
    system, _, code = concept_id.partition(":")
    table = {"CVX": "pool.immunizations", "RXNORM": "pool.medications", "SNOMED": "pool.conditions",
             "LOINC": "pool.observations"}.get(system)
    if not table or not deps.table_exists(db, table):
        return None
    codes = [m.split(":", 1)[1] for m in concepts_mod.CLASS_MEMBERS.get(concept_id, [concept_id])]
    n = db.query(f"SELECT COUNT(DISTINCT pseudo_id) AS n FROM {table} WHERE concept_code IN "
                 f"({', '.join('?' for _ in codes)})", codes)[0]["n"]
    return "<5" if n < sanity.K else str(n)


def get_graph(concept: str | None = None, depth: int = 1, include_rejected: bool = False, limit: int = 400,
              db=None) -> dict:
    db = db or deps.get_db()
    run = latest_run(db)
    if not run:
        return dict(run_id=None, nodes=[], edges=[])
    index = concepts_mod.load_index(db)
    status_sql = "" if include_rejected else " AND status = 'ACCEPTED'"
    all_edges = db.query(f"SELECT * FROM research.edges WHERE run_id = ?{status_sql} ORDER BY edge_id", [run])

    # deterministic ontology links: Moderna IS_A COVID-19 vaccine (any), shown only when the class has edges
    in_graph = {n for e in all_edges for n in (e["src_id"], e["dst_id"])}
    for cls, members in concepts_mod.CLASS_MEMBERS.items():
        if cls in in_graph:
            for m in members:
                if m != cls and (m in in_graph or m == concept):
                    all_edges.append(dict(edge_id=f"ISA-{m}-{cls}", src_id=m, dst_id=cls, relation="IS_A",
                                          status="ONTOLOGY", paper_id=None))
    if concept:
        frontier, keep, seen_nodes = {concept}, {}, {concept}
        for _ in range(max(1, min(depth, 3))):
            nxt = set()
            for e in all_edges:
                if e["src_id"] in frontier or e["dst_id"] in frontier:
                    keep[e["edge_id"]] = e
                    for n in (e["src_id"], e["dst_id"]):
                        if n not in seen_nodes:
                            seen_nodes.add(n)
                            nxt.add(n)
            frontier = nxt
        edges = list(keep.values())
    else:
        edges = all_edges
    edges = edges[:limit]

    isa = [e for e in edges if e["relation"] == "IS_A"]
    edges = [e for e in edges if e["relation"] != "IS_A"]
    pmap = _paper_map(db, {e["paper_id"] for e in edges})
    accepted = [e for e in all_edges if e["status"] == "ACCEPTED"]
    lit = sanity.literature(accepted, {pid: p.get("pub_year") for pid, p in _paper_map(
        db, {e["paper_id"] for e in accepted}).items()})

    concept_ids = sorted({n for e in edges + isa for n in (e["src_id"], e["dst_id"])} | ({concept} if concept else set()))
    nodes = []
    for cid in concept_ids:
        c = index.get(cid)
        nodes.append(dict(node_id=cid, type="concept", label=index.label(cid),
                          code_system=cid.split(":", 1)[0], free=cid.startswith("FREE:"),
                          known=c is not None, pool_patients=pool_patient_count(db, cid)))
    for pid, p in sorted(pmap.items()):
        nodes.append(dict(node_id=pid, type="paper", label=p["title"], year=p["pub_year"], url=p["source_url"]))

    out_edges = [edge_view(e, pmap.get(e["paper_id"]), (lit.get(e["edge_id"]) or {}).get("support_years"))
                 for e in edges]
    out_edges += [dict(edge_id=e["edge_id"], src=e["src_id"], dst=e["dst_id"], relation="IS_A", source="ontology")
                  for e in isa]
    if pmap and deps.table_exists(db, "research.citations"):
        ids = sorted(pmap)
        for c in db.query(f"SELECT * FROM research.citations WHERE citing_paper_id IN ({', '.join('?' for _ in ids)})",
                          ids):
            if c["cited_paper_id"] in pmap:
                out_edges.append(dict(edge_id=c["edge_id"], src=c["citing_paper_id"], dst=c["cited_paper_id"],
                                      relation="CITES"))
    return dict(run_id=run, nodes=nodes, edges=out_edges)


def get_edge(edge_id: str, db=None) -> dict | None:
    db = db or deps.get_db()
    if edge_id.startswith("CIT-"):
        rows = db.query("SELECT * FROM research.citations WHERE edge_id = ?", [edge_id])
        if not rows:
            return None
        c = rows[0]
        return dict(edge_id=edge_id, src=c["citing_paper_id"], dst=c["cited_paper_id"], relation="CITES",
                    lineage=deps.lineage_chain(edge_id))
    rows = db.query("SELECT * FROM research.edges WHERE edge_id = ?", [edge_id])
    if not rows:
        return None
    r = rows[0]
    peers = db.query("SELECT edge_id, src_id, dst_id, relation, paper_id FROM research.edges "
                     "WHERE run_id = ? AND status = 'ACCEPTED'", [r["run_id"]])
    pm = _paper_map(db, {p["paper_id"] for p in peers} | {r["paper_id"]})
    lit = sanity.literature(peers + ([] if r["status"] == "ACCEPTED" else [dict(r)]),
                            {k: v.get("pub_year") for k, v in pm.items()})
    view = edge_view(r, pm.get(r["paper_id"]), (lit.get(edge_id) or {}).get("support_years"))
    view["lineage"] = deps.lineage_chain(edge_id)
    view["run_id"] = r["run_id"]
    return view
