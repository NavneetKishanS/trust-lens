"use client";
import Link from "next/link";
import { useApi } from "@/lib/useApi";
import { RELATION_LABEL, RELATION_TEXT, shortLabel } from "@/lib/kg";
import type { GraphNode, KgEdge, LineageStep } from "@/lib/types";
import ErrorBox from "../ErrorBox";
import LineageChain from "../LineageChain";
import Status, { SyntheticFlag } from "../Status";

type EdgeDetail = KgEdge & { lineage: LineageStep[]; run_id?: string };

function num(s?: string | null): number | null {
  if (!s || s === "<5") return null;
  const v = Number(s);
  return Number.isFinite(v) ? v : null;
}

function PoolEvidence({ edge }: { edge: KgEdge }) {
  const ev = edge.sanity.pool_evidence;
  if (!ev) return <p className="small muted">No pool check recorded.</p>;
  if (edge.sanity.pool === "UNTESTABLE" || !ev.sql)
    return <p className="small muted">{ev.reason ?? "This pair cannot be tested in the anonymised pool."}</p>;
  const e = num(ev.exposed_rate);
  const b = num(ev.baseline_rate);
  const max = Math.max(e ?? 0, b ?? 0, 1);
  return (
    <>
      <div className="rate-bars">
        <div className="rate-bar">
          <span>Exposed</span>
          <span className="track">
            <span className="fill exposed" style={{ width: `${((e ?? 0) / max) * 100}%`, display: "block" }} />
          </span>
          <span className="mono">{ev.exposed_rate ? `${ev.exposed_rate}%` : "suppressed"}</span>
        </div>
        <div className="rate-bar">
          <span>Baseline</span>
          <span className="track">
            <span className="fill" style={{ width: `${((b ?? 0) / max) * 100}%`, display: "block" }} />
          </span>
          <span className="mono">{ev.baseline_rate ? `${ev.baseline_rate}%` : "suppressed"}</span>
        </div>
      </div>
      <dl className="kv" style={{ marginTop: 8 }}>
        <dt>Exposed n</dt>
        <dd>
          {ev.n_exposed ?? "—"} ({ev.n_outcome_exposed ?? "—"} with outcome)
        </dd>
        <dt>Unexposed n</dt>
        <dd>
          {ev.n_unexposed ?? "—"} ({ev.n_outcome_unexposed ?? "—"} with outcome)
        </dd>
        {ev.exposure_codes && ev.exposure_codes.length > 1 && (
          <>
            <dt>Exposure</dt>
            <dd>any of CVX {ev.exposure_codes.join(", ")}</dd>
          </>
        )}
        <dt>Window</dt>
        <dd>{(ev as { params?: { window_days?: number } }).params?.window_days ?? 90} days after first exposure</dd>
      </dl>
      <div className="row" style={{ marginTop: 8 }}>
        <SyntheticFlag label="Synthetic pool · planted signal" />
      </div>
      {ev.note && <p className="tiny muted" style={{ marginTop: 6 }}>{ev.note}</p>}
      <details className="sql" style={{ marginTop: 6 }}>
        <summary>Pool SQL · {ev.sql_source}</summary>
        <pre>{ev.sql}</pre>
      </details>
    </>
  );
}

export function EdgeInspector({ edgeId, nodes }: { edgeId: string; nodes: Map<string, GraphNode> }) {
  const { data: e, error, loading } = useApi<EdgeDetail>(`/research/edges/${encodeURIComponent(edgeId)}`);
  const label = (id: string) => nodes.get(id)?.label ?? id;

  if (error) return <div className="inspector"><ErrorBox message={error} /></div>;
  if (!e || loading)
    return (
      <div className="inspector">
        <div className="skeleton" style={{ height: 18, width: "70%" }} />
        <div className="skeleton" style={{ height: 80, marginTop: 12 }} />
        <div className="skeleton" style={{ height: 120, marginTop: 12 }} />
      </div>
    );

  const doi = e.paper.doi;
  return (
    <div className="inspector">
      <div className="panel-title">Evidence inspector · {RELATION_LABEL[e.relation] ?? e.relation}</div>
      <div className="rel">
        {shortLabel(label(e.src), 60)} <span className="verb">{RELATION_TEXT[e.relation] ?? e.relation}</span> {shortLabel(label(e.dst), 60)}
      </div>
      <div className="row" style={{ marginTop: 8 }}>
        <Status value={e.status} />
        <code className="tiny">{e.edge_id}</code>
      </div>

      <div className="block">
        <h3>Verbatim evidence</h3>
        <div className="quote">“{e.quote}”</div>
        <p className="tiny muted">Copied word for word from the abstract; A2 checks this before the edge is accepted.</p>
      </div>

      <div className="block">
        <h3>Source paper</h3>
        <p className="strong" style={{ marginBottom: 4 }}>{e.paper.title ?? e.paper.paper_id}</p>
        <dl className="kv">
          <dt>Year</dt>
          <dd>{e.paper.year ?? "—"}</dd>
          <dt>Identifier</dt>
          <dd>{e.paper.paper_id}</dd>
          <dt>DOI</dt>
          <dd>{doi ? <a href={`https://doi.org/${doi}`} target="_blank" rel="noreferrer">{doi}</a> : "—"}</dd>
          <dt>Europe PMC</dt>
          <dd><a href={e.paper.url} target="_blank" rel="noreferrer">Open paper ↗</a></dd>
        </dl>
      </div>

      <div className="block">
        <h3>A2 critic (deterministic)</h3>
        <div className="row">
          <Status value={e.critic.status} />
        </div>
        {e.critic.reasons.length > 0 ? (
          <ul className="small" style={{ margin: "6px 0 0 18px", padding: 0 }}>
            {e.critic.reasons.map((r) => <li key={r}>{r}</li>)}
          </ul>
        ) : (
          <p className="small muted" style={{ marginTop: 6 }}>Quote verbatim, both entities named in it, negation consistent with the relation.</p>
        )}
      </div>

      <div className="block">
        <h3>A3 sanity check: literature vs anonymised pool</h3>
        <div className="verdict-pair">
          <div className="verdict-box">
            <div className="h">Literature</div>
            {e.sanity.literature ? <Status value={e.sanity.literature} /> : <span className="muted small">not checked</span>}
            <div className="small" style={{ marginTop: 6 }}>
              {e.sanity.support_count ?? 0} supporting · {e.sanity.contradict_count ?? 0} contradicting papers
            </div>
            {e.sanity.support_years && (
              <div className="tiny muted">Supporting years {e.sanity.support_years.oldest}–{e.sanity.support_years.newest}</div>
            )}
          </div>
          <div className="verdict-box">
            <div className="h">Clinical pool</div>
            {e.sanity.pool ? <Status value={e.sanity.pool} /> : <span className="muted small">not checked</span>}
            <div className="tiny muted" style={{ marginTop: 6 }}>Association only, not causation.</div>
          </div>
        </div>
        <div style={{ marginTop: 10 }}>
          <PoolEvidence edge={e} />
        </div>
      </div>

      <div className="block">
        <h3>Lineage · agents and models</h3>
        <LineageChain id={e.edge_id} chain={e.lineage} />
      </div>

      <div className="block">
        <Link className="btn secondary sm" href="/ask?q=hypertension_after_moderna">Test in Ask the Data →</Link>
      </div>
    </div>
  );
}

export function NodeInspector({
  node,
  edges,
  nodes,
  onSelectEdge,
  onFocus,
}: {
  node: GraphNode;
  edges: KgEdge[];
  nodes: Map<string, GraphNode>;
  onSelectEdge: (id: string) => void;
  onFocus: (id: string) => void;
}) {
  const related = edges.filter((e) => e.src === node.node_id || e.dst === node.node_id || e.paper.paper_id === node.node_id);
  return (
    <div className="inspector">
      <div className="panel-title">{node.type === "paper" ? "Paper" : "Concept"}</div>
      <div className="rel">{node.label}</div>
      <dl className="kv" style={{ marginTop: 10 }}>
        <dt>Identifier</dt>
        <dd><code>{node.node_id}</code></dd>
        {node.type === "concept" && (
          <>
            <dt>Code system</dt>
            <dd>{node.free ? "Uncoded (FREE)" : node.code_system}</dd>
            <dt>Pool patients</dt>
            <dd>{node.pool_patients ?? "not in the pool"}</dd>
          </>
        )}
        {node.type === "paper" && (
          <>
            <dt>Year</dt>
            <dd>{node.year ?? "—"}</dd>
            <dt>Europe PMC</dt>
            <dd>{node.url ? <a href={node.url} target="_blank" rel="noreferrer">Open paper ↗</a> : "—"}</dd>
          </>
        )}
      </dl>
      {node.type === "concept" && (
        <div className="row" style={{ marginTop: 10 }}>
          <button className="secondary sm" onClick={() => onFocus(node.node_id)}>Centre graph on this concept</button>
        </div>
      )}
      <div className="block" style={{ marginTop: 10 }}>
        <h3>{related.length} relationship{related.length === 1 ? "" : "s"} in view</h3>
        {related.map((e) => (
          <button key={e.edge_id} className="sentence" onClick={() => onSelectEdge(e.edge_id)}>
            <span className="small">
              {shortLabel(nodes.get(e.src)?.label ?? e.src, 28)} <span className="muted">{RELATION_TEXT[e.relation] ?? e.relation}</span>{" "}
              {shortLabel(nodes.get(e.dst)?.label ?? e.dst, 28)}
            </span>
            <span className="meta">
              <Status value={e.status} />
              {e.sanity.literature && <Status value={e.sanity.literature} />}
              {e.sanity.pool && <Status value={e.sanity.pool} />}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
