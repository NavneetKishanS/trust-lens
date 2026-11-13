"use client";
import { useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { isKgEdge, type BuildResult, type Graph, type GraphNode, type KgEdge, type LineageStep } from "@/lib/types";
import Drawer from "./Drawer";
import ErrorBox from "./ErrorBox";
import LineageChain from "./LineageChain";
import Status from "./Status";

const RELATION_TEXT: Record<string, string> = {
  ASSOCIATED_WITH: "is associated with",
  INCREASES_RISK_OF: "increases risk of",
  DECREASES_RISK_OF: "decreases risk of",
  ADVERSE_EVENT_OF: "is an adverse event of",
  TREATS: "treats",
  NO_ASSOCIATION_WITH: "has no association with",
};

function PoolEvidenceBox({ edge }: { edge: KgEdge }) {
  const ev = edge.sanity.pool_evidence;
  if (!ev) return null;
  if (edge.sanity.pool !== "OBSERVED" && edge.sanity.pool !== "NOT_OBSERVED")
    return <p className="small muted">Pool check: {ev.reason ?? "not testable"}</p>;
  return (
    <div className="notice small" style={{ marginTop: 6 }}>
      <b>Anonymised pool (synthetic):</b> exposed {ev.exposed_rate ?? "suppressed"}% (n={ev.n_exposed}) vs baseline{" "}
      {ev.baseline_rate ?? "suppressed"}% (n={ev.n_unexposed}).{" "}
      {ev.exposure_codes && ev.exposure_codes.length > 1 && <>Exposure = any of CVX {ev.exposure_codes.join(", ")}. </>}
      {ev.note}
    </div>
  );
}

// Knowledge graph: build (A1 → A2 → A3), then list cited edges around a concept. Every edge shows its verbatim quote,
// the paper link, the critic result and the sanity labels.
export default function GraphPanel() {
  const [concept, setConcept] = useState("CVX:207");
  const [depth, setDepth] = useState(2);
  const [showRejected, setShowRejected] = useState(false);
  const [actionError, setError] = useState<string | null>(null);
  const [building, setBuilding] = useState(false);
  const [build, setBuild] = useState<BuildResult | null>(null);
  const [open, setOpen] = useState<(KgEdge & { lineage?: LineageStep[] }) | null>(null);

  const q = new URLSearchParams({ depth: String(depth), include_rejected: String(showRejected) });
  if (concept.trim()) q.set("concept", concept.trim());
  const { data: graph, error: loadError, reload: load } = useApi<Graph>(`/research/graph?${q}`);
  const error = actionError ?? loadError;

  async function runBuild(plant: boolean) {
    setBuilding(true);
    const r = await api<BuildResult>("/research/graph/build", {
      method: "POST",
      body: { topic: "covid_vaccine_safety", max_papers: 200, inject_fabricated_quote: plant },
    });
    setBuilding(false);
    if (r.ok) {
      setBuild(r.data);
      setError(null);
      load();
    } else setError(r.message);
  }

  async function openEdge(e: KgEdge) {
    const r = await api<KgEdge & { lineage: LineageStep[] }>(`/research/edges/${encodeURIComponent(e.edge_id)}`);
    setOpen(r.ok ? r.data : e);
  }

  const nodes = useMemo(() => new Map<string, GraphNode>((graph?.nodes ?? []).map((n) => [n.node_id, n])), [graph]);
  const label = (id: string) => {
    const n = nodes.get(id);
    return n ? n.label : id;
  };
  const kgEdges = (graph?.edges ?? []).filter(isKgEdge);
  const isa = (graph?.edges ?? []).filter((e) => e.relation === "IS_A");
  const cites = (graph?.edges ?? []).filter((e) => e.relation === "CITES");
  const concepts = (graph?.nodes ?? []).filter((n) => n.type === "concept");

  return (
    <div className="card">
      <h2>Research knowledge graph</h2>
      <p className="small muted">
        A1 proposes a relation with a verbatim quote, A2 checks the quote and entities deterministically, A3 compares it with other
        papers and with our anonymised pool. Pool numbers are synthetic and include a planted signal.
      </p>
      <div className="row">
        <label className="small">
          Concept <input type="text" value={concept} onChange={(e) => setConcept(e.target.value)} size={18} />
        </label>
        <label className="small">
          Depth{" "}
          <select value={depth} onChange={(e) => setDepth(Number(e.target.value))}>
            <option value={1}>1</option>
            <option value={2}>2</option>
            <option value={3}>3</option>
          </select>
        </label>
        <label className="row small">
          <input type="checkbox" checked={showRejected} onChange={(e) => setShowRejected(e.target.checked)} /> show rejected
        </label>
        <span className="spacer" />
        <button className="secondary" disabled={building} onClick={() => runBuild(true)} title="PL5: one fabricated quote is planted; A2 must reject it">
          Build + plant fabricated quote
        </button>
        <button disabled={building} onClick={() => runBuild(false)}>
          {building ? "Building…" : "Build graph"}
        </button>
      </div>
      {build && (
        <p className="small" style={{ marginTop: 8 }}>
          Run <code>{build.run_id}</code>: {build.papers} papers → {build.candidate_edges} candidate edges →{" "}
          <Status value="ACCEPTED" label={`${build.accepted} accepted`} /> <Status value="REJECTED" label={`${build.rejected} rejected`} /> ·
          audit #{build.audit_seq}
        </p>
      )}
      {error && <div style={{ marginTop: 10 }}><ErrorBox message={error} /></div>}
      {graph && !graph.run_id && <p className="muted">No graph yet. Build it first.</p>}

      {graph?.run_id && (
        <>
          <p className="small muted" style={{ marginTop: 10 }}>
            Run {graph.run_id} · {kgEdges.length} relation edges · {cites.length} citation links ·{" "}
            {concepts.length} concepts
          </p>
          {concepts.length > 0 && (
            <div className="row small" style={{ marginBottom: 8 }}>
              {concepts.map((n) =>
                n.type === "concept" ? (
                  <button key={n.node_id} className="chip" onClick={() => setConcept(n.node_id)} title={n.node_id}>
                    <span className={n.free ? "node-free" : undefined}>{n.label}</span>
                    {n.pool_patients && <span className="muted"> · pool {n.pool_patients}</span>}
                  </button>
                ) : null,
              )}
            </div>
          )}
          {isa.map((e) => (
            <p key={e.edge_id} className="small muted">
              Ontology: <b>{label(e.src)}</b> is a <b>{label(e.dst)}</b> (deterministic link, not an agent claim)
            </p>
          ))}
          {kgEdges.map((e) => (
            <div key={e.edge_id} className={`edge ${e.status === "REJECTED" ? "rejected" : ""}`}>
              <h4>
                <span className={nodes.get(e.src)?.type === "concept" && (nodes.get(e.src) as { free?: boolean }).free ? "node-free" : undefined}>
                  {label(e.src)}
                </span>{" "}
                <span className="muted">{RELATION_TEXT[e.relation] ?? e.relation}</span>{" "}
                <span className={nodes.get(e.dst)?.type === "concept" && (nodes.get(e.dst) as { free?: boolean }).free ? "node-free" : undefined}>
                  {label(e.dst)}
                </span>
              </h4>
              <div className="row">
                <Status value={e.status} />
                {e.sanity.literature && (
                  <Status
                    value={e.sanity.literature}
                    title={`${e.sanity.support_count ?? 0} supporting, ${e.sanity.contradict_count ?? 0} contradicting papers`}
                  />
                )}
                {e.sanity.pool && <Status value={e.sanity.pool} />}
                {e.critic.status === "FAIL" && <Status value="FAIL" />}
                <span className="small muted">
                  {e.sanity.support_count ?? 0} support · {e.sanity.contradict_count ?? 0} contradict
                  {e.sanity.support_years && ` · ${e.sanity.support_years.oldest}–${e.sanity.support_years.newest}`}
                </span>
              </div>
              <div className="quote">“{e.quote}”</div>
              {e.critic.reasons.length > 0 && <div className="error small">A2 critic: {e.critic.reasons.join("; ")}</div>}
              <PoolEvidenceBox edge={e} />
              <div className="row small" style={{ marginTop: 6 }}>
                <a href={e.paper.url} target="_blank" rel="noreferrer">
                  {e.paper.title ?? e.paper.paper_id}
                </a>
                <span className="muted">
                  {e.paper.year} · {e.paper.paper_id}
                </span>
                <span className="spacer" />
                <button className="secondary" onClick={() => openEdge(e)}>
                  Lineage
                </button>
              </div>
            </div>
          ))}
        </>
      )}

      {open && (
        <Drawer title="Edge lineage" onClose={() => setOpen(null)}>
          <p>
            <b>{label(open.src)}</b> {RELATION_TEXT[open.relation] ?? open.relation} <b>{label(open.dst)}</b>
          </p>
          <div className="quote">“{open.quote}”</div>
          <p className="small">
            <a href={open.paper.url} target="_blank" rel="noreferrer">
              {open.paper.url}
            </a>
          </p>
          {open.sanity.pool_evidence?.sql && (
            <>
              <h3>Pool check SQL ({open.sanity.pool_evidence.sql_source})</h3>
              <pre>{open.sanity.pool_evidence.sql}</pre>
            </>
          )}
          <h3>Lineage</h3>
          <LineageChain id={open.edge_id} chain={open.lineage} />
        </Drawer>
      )}
    </div>
  );
}
