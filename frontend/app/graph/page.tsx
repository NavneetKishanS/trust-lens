"use client";
import { Suspense, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { LIT_COLOR, REJECTED_COLOR, RELATION_LABEL, RELATION_TEXT, SUGGESTED_CONCEPTS, SYSTEM_COLOR, SYSTEM_LABEL, shortLabel } from "@/lib/kg";
import { isKgEdge, type BuildResult, type Graph, type GraphNode, type KgEdge, type LinkEdge } from "@/lib/types";
import GraphCanvas, { type EvidenceLink } from "@/components/kg/GraphCanvas";
import { EdgeInspector, NodeInspector } from "@/components/kg/EdgeInspector";
import ErrorBox from "@/components/ErrorBox";
import PageHead from "@/components/PageHead";
import Term from "@/components/Term";
import Icon from "@/components/Icon";
import Status from "@/components/Status";

const LIT = ["CONSISTENT", "CONTESTED", "SINGLE_SOURCE"] as const;
const POOL = ["OBSERVED", "NOT_OBSERVED", "UNTESTABLE"] as const;

function toggle(set: Set<string>, v: string): Set<string> {
  const n = new Set(set);
  if (n.has(v)) n.delete(v);
  else n.add(v);
  return n;
}

function KnowledgeGraph() {
  const params = useSearchParams();
  const [concept, setConcept] = useState(params.get("concept") ?? "CVX:207");
  const [draft, setDraft] = useState(concept);
  const [depth, setDepth] = useState(Number(params.get("depth") ?? 2));
  const [view, setView] = useState<"graph" | "list">("graph");
  const [selEdge, setSelEdge] = useState<string | null>(params.get("edge"));
  const [selNode, setSelNode] = useState<string | null>(null);

  const [showConcepts, setShowConcepts] = useState(true);
  const [showPapers, setShowPapers] = useState(true);
  const [showCites, setShowCites] = useState(true);
  const [showIsa, setShowIsa] = useState(true);
  const [showPaperLabels, setShowPaperLabels] = useState(false);
  const [statusF, setStatusF] = useState(new Set(["ACCEPTED"]));
  const [litF, setLitF] = useState(new Set<string>(LIT));
  const [poolF, setPoolF] = useState(new Set<string>(POOL));
  const [relOff, setRelOff] = useState(new Set<string>());

  const [building, setBuilding] = useState(false);
  const [build, setBuild] = useState<BuildResult | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const q = new URLSearchParams({ depth: String(depth), include_rejected: "true" });
  if (concept.trim()) q.set("concept", concept.trim());
  const { data: graph, error, loading, reload } = useApi<Graph>(`/research/graph?${q}`);
  const { data: catalog } = useApi<Graph>("/research/graph?include_rejected=true");

  const nodeMap = useMemo(() => {
    const m = new Map<string, GraphNode>();
    for (const n of catalog?.nodes ?? []) m.set(n.node_id, n);
    for (const n of graph?.nodes ?? []) m.set(n.node_id, n);
    return m;
  }, [graph, catalog]);

  const allRel = useMemo(() => (graph?.edges ?? []).filter(isKgEdge), [graph]);
  const allLinks = useMemo(() => (graph?.edges ?? []).filter((e): e is LinkEdge => !isKgEdge(e)), [graph]);
  const relTypes = useMemo(() => {
    const c = new Map<string, number>();
    for (const e of allRel) c.set(e.relation, (c.get(e.relation) ?? 0) + 1);
    return [...c.entries()].sort((a, b) => b[1] - a[1]);
  }, [allRel]);
  const countBy = (f: (e: KgEdge) => string | null) => {
    const c = new Map<string, number>();
    for (const e of allRel) {
      const k = f(e);
      if (k) c.set(k, (c.get(k) ?? 0) + 1);
    }
    return c;
  };
  const statusCount = countBy((e) => e.status);
  const litCount = countBy((e) => (e.status === "ACCEPTED" ? e.sanity.literature : null));
  const poolCount = countBy((e) => (e.status === "ACCEPTED" ? e.sanity.pool : null));

  const visibleRel = useMemo(
    () =>
      showConcepts
        ? allRel.filter(
            (e) =>
              statusF.has(e.status) &&
              !relOff.has(e.relation) &&
              (e.status === "REJECTED" || ((!e.sanity.literature || litF.has(e.sanity.literature)) && (!e.sanity.pool || poolF.has(e.sanity.pool)))),
          )
        : [],
    [allRel, statusF, relOff, litF, poolF, showConcepts],
  );

  const { nodes, links, evidence } = useMemo(() => {
    const keep = new Set<string>();
    for (const e of visibleRel) {
      keep.add(e.src);
      keep.add(e.dst);
    }
    if (concept && showConcepts && nodeMap.has(concept)) keep.add(concept);
    const papers = new Set<string>();
    const ev: EvidenceLink[] = [];
    if (showPapers) {
      for (const e of visibleRel) {
        papers.add(e.paper.paper_id);
        for (const c of [e.src, e.dst]) ev.push({ id: `${e.edge_id}-${c}`, paper: e.paper.paper_id, concept: c });
      }
    }
    const lk = allLinks.filter((l) => {
      if (l.relation === "IS_A") return showIsa && showConcepts && keep.has(l.src) && keep.has(l.dst);
      return showCites && showPapers && papers.has(l.src) && papers.has(l.dst);
    });
    const dedupEv = [...new Map(ev.map((v) => [`${v.paper}~${v.concept}`, v])).values()];
    const ns = (graph?.nodes ?? []).filter((n) => (n.type === "paper" ? papers.has(n.node_id) : keep.has(n.node_id)));
    return { nodes: ns, links: lk, evidence: dedupEv };
  }, [visibleRel, allLinks, graph, concept, showPapers, showCites, showIsa, showConcepts, nodeMap]);

  const conceptOptions = useMemo(() => {
    const seen = new Map<string, string>();
    for (const s of SUGGESTED_CONCEPTS) seen.set(s.id, s.label);
    for (const n of catalog?.nodes ?? []) if (n.type === "concept" && !seen.has(n.node_id)) seen.set(n.node_id, n.label);
    return [...seen.entries()];
  }, [catalog]);

  function focus(id: string) {
    setConcept(id);
    setDraft(id);
    setSelEdge(null);
    setSelNode(null);
  }
  function applySearch() {
    const t = draft.trim();
    if (!t) return focus("");
    const exact = conceptOptions.find(([id, label]) => id.toLowerCase() === t.toLowerCase() || label.toLowerCase() === t.toLowerCase());
    const partial = conceptOptions.find(([id, label]) => label.toLowerCase().includes(t.toLowerCase()) || id.toLowerCase().includes(t.toLowerCase()));
    focus((exact ?? partial)?.[0] ?? t);
  }
  async function runBuild(plant: boolean) {
    setBuilding(true);
    setActionError(null);
    const r = await api<BuildResult>("/research/graph/build", {
      method: "POST",
      body: { topic: "covid_vaccine_safety", max_papers: 200, inject_fabricated_quote: plant },
    });
    setBuilding(false);
    if (r.ok) {
      setBuild(r.data);
      setSelEdge(null);
      reload();
    } else setActionError(r.message);
  }

  const selNodeObj = selNode ? nodeMap.get(selNode) : undefined;
  const contested = visibleRel.filter((e) => e.sanity.literature === "CONTESTED");

  return (
    <div className="content wide">
      <PageHead
        eyebrow="Research · Literature"
        title="Knowledge Graph"
        sub={
          <>
            Each line is a relationship found in a published paper. Click one to read the exact sentence it came from, and whether other papers and our patient data agree.
            {graph?.run_id && <span className="faint"> · Build {graph.run_id}</span>}
          </>
        }
        actions={
          <>
            <div className="seg" role="tablist">
              <button className={view === "graph" ? "on" : ""} onClick={() => setView("graph")}>Graph</button>
              <button className={view === "list" ? "on" : ""} onClick={() => setView("list")}>List</button>
            </div>
          </>
        }
      />
      {(error || actionError) && <div style={{ marginBottom: 12 }}><ErrorBox message={(actionError ?? error)!} /></div>}

      <div className="kg">
        {/* ------------------------------------------------ left: search, filters, controls */}
        <div className="kg-left">
          <div className="group">
            <div className="panel-title">Concept</div>
            <form
              className="stack"
              onSubmit={(e) => {
                e.preventDefault();
                applySearch();
              }}
            >
              <input type="search" list="kg-concepts" value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="e.g. CVX:207 or hypertension" />
              <datalist id="kg-concepts">
                {conceptOptions.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
              </datalist>
              <div className="row">
                <select value={depth} onChange={(e) => setDepth(Number(e.target.value))} title="Hops from the concept">
                  <option value={1}>Depth 1</option>
                  <option value={2}>Depth 2</option>
                  <option value={3}>Depth 3</option>
                </select>
                <button type="submit" className="sm">Explore</button>
                <button type="button" className="ghost sm" onClick={() => focus("")} title="Show the whole graph">All</button>
              </div>
            </form>
            <div className="row" style={{ marginTop: 8 }}>
              {SUGGESTED_CONCEPTS.map((s) => (
                <button key={s.id} className="chip" onClick={() => focus(s.id)} style={concept === s.id ? { background: "var(--navy-50)" } : undefined}>
                  {s.label}
                </button>
              ))}
            </div>
          </div>

          <div className="group">
            <div className="panel-title">Nodes</div>
            <label className="check"><input type="checkbox" checked={showConcepts} onChange={() => setShowConcepts(!showConcepts)} /> Concepts</label>
            <label className="check"><input type="checkbox" checked={showPapers} onChange={() => setShowPapers(!showPapers)} /> Papers</label>
            <label className="check"><input type="checkbox" checked={showPaperLabels} onChange={() => setShowPaperLabels(!showPaperLabels)} /> Paper years</label>
          </div>

          <details className="more filters-more">
            <summary>More filters and tools</summary>
            <div style={{ marginTop: 10 }}>
          <div className="group">
            <div className="panel-title">Connections</div>
            <label className="check"><input type="checkbox" checked={showCites} onChange={() => setShowCites(!showCites)} /> Citations (CITES)<span className="count">{allLinks.filter((l) => l.relation === "CITES").length}</span></label>
            <label className="check"><input type="checkbox" checked={showIsa} onChange={() => setShowIsa(!showIsa)} /> Ontology (IS_A)<span className="count">{allLinks.filter((l) => l.relation === "IS_A").length}</span></label>
          </div>

          <div className="group">
            <div className="panel-title">Relationship type</div>
            {relTypes.length === 0 && <p className="tiny muted">None in view.</p>}
            {relTypes.map(([r, n]) => (
              <label key={r} className="check">
                <input type="checkbox" checked={!relOff.has(r)} onChange={() => setRelOff(toggle(relOff, r))} /> {RELATION_LABEL[r] ?? r}
                <span className="count">{n}</span>
              </label>
            ))}
          </div>

          <div className="group">
            <div className="panel-title"><Term k="a2">Quote check</Term></div>
            {["ACCEPTED", "REJECTED"].map((s) => (
              <label key={s} className="check">
                <input type="checkbox" checked={statusF.has(s)} onChange={() => setStatusF(toggle(statusF, s))} /> {s === "ACCEPTED" ? "Accepted" : "Rejected"}
                <span className="count">{statusCount.get(s) ?? 0}</span>
              </label>
            ))}
          </div>

          <div className="group">
            <div className="panel-title"><Term k="a3">Other papers</Term></div>
            {LIT.map((s) => (
              <label key={s} className="check">
                <input type="checkbox" checked={litF.has(s)} onChange={() => setLitF(toggle(litF, s))} />
                <span style={{ width: 10, height: 3, background: LIT_COLOR[s], display: "inline-block" }} /> {s === "SINGLE_SOURCE" ? "Single source" : s[0] + s.slice(1).toLowerCase()}
                <span className="count">{litCount.get(s) ?? 0}</span>
              </label>
            ))}
          </div>

          <div className="group">
            <div className="panel-title"><Term k="a3">Patient data</Term></div>
            {POOL.map((s) => (
              <label key={s} className="check">
                <input type="checkbox" checked={poolF.has(s)} onChange={() => setPoolF(toggle(poolF, s))} /> {s === "NOT_OBSERVED" ? "Not observed" : s[0] + s.slice(1).toLowerCase()}
                <span className="count">{poolCount.get(s) ?? 0}</span>
              </label>
            ))}
          </div>

          <div className="group">
            <div className="panel-title">Graph build</div>
            <div className="stack">
              <button className="secondary sm" disabled={building} onClick={() => runBuild(false)}>
                {building ? <><span className="spinner dark" /> Building…</> : "Rebuild graph"}
              </button>
              <button className="secondary sm" disabled={building} onClick={() => runBuild(true)} title="PL5: plants one fabricated quote; the A2 critic must reject it">
                Rebuild + plant fabricated quote
              </button>
              {build && (
                <div className="tiny muted">
                  {build.papers} papers → {build.candidate_edges} candidates → {build.accepted} accepted, {build.rejected} rejected · audit #{build.audit_seq}
                </div>
              )}
            </div>
          </div>
            </div>
          </details>
        </div>

        {/* ------------------------------------------------ centre */}
        <div className="kg-center">
          <div className="kg-toolbar">
            <span className="small">
              <b>{concept ? shortLabel(nodeMap.get(concept)?.label ?? concept, 48) : "Whole graph"}</b>
              <span className="muted"> · {visibleRel.length} relationships · {nodes.filter((n) => n.type === "concept").length} concepts · {nodes.filter((n) => n.type === "paper").length} papers</span>
            </span>
            <span className="spacer" />
            {contested.length > 0 && (
              <button className="chip" onClick={() => (setSelEdge(contested[0].edge_id), setSelNode(null))} title="Select a relationship where papers disagree">
                <Icon name="alert" size={13} /> {contested.length} where papers disagree
              </button>
            )}
            {loading && <span className="spinner dark" />}
          </div>

          {view === "graph" ? (
            <div style={{ flex: 1, position: "relative", display: "flex" }}>
              {graph && !graph.run_id ? (
                <div className="kg-empty">
                  <div>No knowledge graph has been built yet.</div>
                  <button onClick={() => runBuild(false)} disabled={building}>Build graph</button>
                </div>
              ) : nodes.length === 0 && graph ? (
                <div className="kg-empty">
                  <div>No relationships match these filters{concept ? ` around ${concept}` : ""}.</div>
                  <button className="secondary sm" onClick={() => focus("")}>Show the whole graph</button>
                </div>
              ) : (
                <GraphCanvas
                  nodes={nodes}
                  edges={visibleRel}
                  links={links}
                  evidence={evidence}
                  focusId={concept || null}
                  selectedEdge={selEdge}
                  selectedNode={selNode}
                  onSelectEdge={(id) => (setSelEdge(id), setSelNode(null))}
                  onSelectNode={(id) => (setSelNode(id), setSelEdge(null))}
                  showPaperLabels={showPaperLabels}
                />
              )}
              <div className="kg-legend">
                <span><span className="dot" style={{ background: SYSTEM_COLOR.CVX }} />{SYSTEM_LABEL.CVX}</span>
                <span><span className="sw" style={{ borderColor: LIT_COLOR.CONSISTENT }} />Consistent</span>
                <span><span className="dot" style={{ background: SYSTEM_COLOR.SNOMED }} />{SYSTEM_LABEL.SNOMED}</span>
                <span><span className="sw" style={{ borderColor: LIT_COLOR.CONTESTED }} />Contested</span>
                <span><span className="dot" style={{ background: "#fff", border: `1.5px dashed ${SYSTEM_COLOR.FREE}` }} />{SYSTEM_LABEL.FREE}</span>
                <span><span className="sw" style={{ borderColor: LIT_COLOR.SINGLE_SOURCE }} />Single source</span>
                <span><span className="sq" style={{ border: "1.5px solid #8ea3ad" }} />Paper</span>
                <span><span className="sw" style={{ borderColor: REJECTED_COLOR, borderTopStyle: "dashed" }} />Rejected by A2</span>
                <span><span className="sw" style={{ borderColor: "#b9c6cc", borderTopStyle: "dotted" }} />Citation</span>
                <span><span className="sw" style={{ borderColor: "#0e7490", borderTopStyle: "dashed" }} />Ontology (IS_A)</span>
              </div>
            </div>
          ) : (
            <div className="table-wrap" style={{ flex: 1 }}>
              <table>
                <thead>
                  <tr>
                    <th>Relationship</th>
                    <th>A2</th>
                    <th>Literature</th>
                    <th>Pool</th>
                    <th className="num">Year</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleRel.map((e) => (
                    <tr key={e.edge_id} className={`clickable ${selEdge === e.edge_id ? "selected" : ""}`} onClick={() => (setSelEdge(e.edge_id), setSelNode(null))}>
                      <td>
                        <div className="strong small">
                          {shortLabel(nodeMap.get(e.src)?.label ?? e.src, 40)} <span className="muted">{RELATION_TEXT[e.relation] ?? e.relation}</span>{" "}
                          {shortLabel(nodeMap.get(e.dst)?.label ?? e.dst, 40)}
                        </div>
                        <div className="tiny muted" style={{ maxWidth: 560 }}>“{e.quote.length > 160 ? e.quote.slice(0, 160) + "…" : e.quote}”</div>
                      </td>
                      <td><Status value={e.status} /></td>
                      <td>{e.sanity.literature ? <Status value={e.sanity.literature} /> : "—"}</td>
                      <td>{e.sanity.pool ? <Status value={e.sanity.pool} /> : "—"}</td>
                      <td className="num">{e.paper.year ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {visibleRel.length === 0 && <div className="empty">No relationships match these filters.</div>}
            </div>
          )}
        </div>

        {/* ------------------------------------------------ right: evidence inspector */}
        <div className="kg-right">
          {selEdge ? (
            <EdgeInspector key={selEdge} edgeId={selEdge} nodes={nodeMap} />
          ) : selNodeObj ? (
            <NodeInspector node={selNodeObj} edges={visibleRel} nodes={nodeMap} onSelectEdge={(id) => (setSelEdge(id), setSelNode(null))} onFocus={focus} />
          ) : (
            <div className="inspector">
              <div className="panel-title">Evidence inspector</div>
              <h3 style={{ marginTop: 4 }}>How to read this graph</h3>
              <ul className="small" style={{ margin: "0 0 8px", paddingLeft: 18, color: "var(--text-2)" }}>
                <li><b>Circles</b> are medical concepts (vaccines, conditions). <b>Squares</b> are papers.</li>
                <li><b>Lines</b> are relationships a paper states. <span style={{ color: "var(--amber-700)" }}>Amber</span> means <Term k="contested">papers disagree</Term>.</li>
                <li><b>Click a line</b> to see the quote, the paper, and whether our data agrees.</li>
              </ul>
              {contested.length > 0 && (
                <>
                  <h3 style={{ marginTop: 14 }}>Contested in this view</h3>
                  {contested.slice(0, 6).map((e) => (
                    <button key={e.edge_id} className="sentence warn" onClick={() => setSelEdge(e.edge_id)}>
                      <span className="small">
                        {shortLabel(nodeMap.get(e.src)?.label ?? e.src, 30)} <span className="muted">{RELATION_TEXT[e.relation]}</span> {shortLabel(nodeMap.get(e.dst)?.label ?? e.dst, 30)}
                      </span>
                      <span className="meta"><Status value="CONTESTED" /><span className="tiny muted">{e.sanity.support_count} support · {e.sanity.contradict_count} contradict</span></span>
                    </button>
                  ))}
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function GraphPage() {
  return (
    <Suspense fallback={<div className="content">Loading…</div>}>
      <KnowledgeGraph />
    </Suspense>
  );
}
