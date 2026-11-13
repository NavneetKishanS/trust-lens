"use client";
import { Fragment, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import type { AuditEvent, AuditVerify, Health } from "@/lib/types";
import ErrorBox from "@/components/ErrorBox";
import LineageChain from "@/components/LineageChain";
import PageHead from "@/components/PageHead";
import Status from "@/components/Status";

export default function TrustAudit() {
  const { data: events, error: loadError, reload } = useApi<AuditEvent[]>("/audit?limit=500");
  const { data: health } = useApi<Health>("/health");
  const [verify, setVerify] = useState<(AuditVerify & { at: string }) | null>(null);
  const [checking, setChecking] = useState(false);
  const [verifyError, setVerifyError] = useState<string | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [actionF, setActionF] = useState("");
  const [search, setSearch] = useState("");
  const [lineageId, setLineageId] = useState("");
  const [lineageShown, setLineageShown] = useState<string | null>(null);

  async function runVerify() {
    setChecking(true);
    const r = await api<AuditVerify>("/audit/verify");
    setChecking(false);
    if (r.ok) {
      setVerify({ ...r.data, at: new Date().toLocaleTimeString() });
      setVerifyError(null);
    } else setVerifyError(r.message);
  }

  const actions = useMemo(() => {
    const c = new Map<string, number>();
    for (const e of events ?? []) c.set(e.action_type, (c.get(e.action_type) ?? 0) + 1);
    return [...c.entries()].sort((a, b) => b[1] - a[1]);
  }, [events]);
  const shown = (events ?? []).filter(
    (e) => (!actionF || e.action_type === actionF) && (!search || `${e.subject} ${e.actor}`.toLowerCase().includes(search.toLowerCase())),
  );
  const latest = events?.[0];

  return (
    <div className="content">
      <PageHead
        eyebrow="Governance"
        title="Trust & Audit"
        sub="Every action (graph builds, accepted and rejected edges, queries, refusals, reviews) is appended to a hash chain. Each row's hash covers the previous hash and its own content, so changing any row breaks every hash after it."
      />

      <div className="integrity">
        <div className={`seal ${verify ? (verify.valid ? "valid" : "broken") : ""}`}>
          <div className="panel-title">Audit-chain integrity</div>
          {verify ? (
            verify.valid ? (
              <>
                <div className="big" style={{ color: "#2b6e1a" }}>✓ Chain intact</div>
                <div className="small muted">{verify.length} events recomputed from the genesis hash · checked {verify.at}</div>
              </>
            ) : (
              <>
                <div className="big" style={{ color: "var(--red-700)" }}>✕ Chain broken at event #{verify.broken_at}</div>
                <div className="small muted">Recomputed {verify.length} events · checked {verify.at}. Event #{verify.broken_at} or an earlier one was changed.</div>
              </>
            )
          ) : (
            <>
              <div className="big">Not checked yet</div>
              <div className="small muted">Recompute every hash from the first event.</div>
            </>
          )}
          <button className="primary" style={{ marginTop: 10 }} onClick={runVerify} disabled={checking}>
            {checking ? <><span className="spinner" /> Recomputing…</> : "Verify integrity"}
          </button>
          {verifyError && <div style={{ marginTop: 8 }}><ErrorBox message={verifyError} /></div>}
        </div>
        <div className="metric navy">
          <div className="k">Events in the log</div>
          <div className="v">{latest ? latest.seq : "—"}</div>
          <div className="d">{latest ? `latest: ${latest.action_type}` : ""}</div>
        </div>
        <div className={`metric ${health?.db === "exasol" ? "accent" : "amber"}`}>
          <div className="k">Database</div>
          <div className="v" style={{ fontSize: 18 }}>{health ? (health.db === "exasol" ? "Exasol" : "DuckDB (local)") : "—"}</div>
          <div className="d">{health?.db === "exasol" ? "Data and SQL run in Exasol" : "Local fallback, not Exasol"}</div>
        </div>
        <div className={`metric ${health && health.llm !== "stub" ? "accent" : "amber"}`}>
          <div className="k">AI provider</div>
          <div className="v" style={{ fontSize: 18 }}>{health ? (health.llm === "stub" ? "Stub mode" : health.llm === "bedrock" ? "Claude · Bedrock EU" : "Claude · Anthropic") : "—"}</div>
          <div className="d">{health?.llm === "stub" ? "Deterministic templates, no LLM calls" : "Agents call Claude"}</div>
        </div>
      </div>

      <div className="grid2" style={{ gridTemplateColumns: "1fr 380px", alignItems: "start" }}>
        <div className="card flush">
          <div className="card-head">
            <h2>Event history</h2>
            <span className="hint">GET /audit · newest first</span>
            <span className="spacer" />
            <input type="search" placeholder="Filter subject or actor" value={search} onChange={(e) => setSearch(e.target.value)} />
            <select value={actionF} onChange={(e) => setActionF(e.target.value)}>
              <option value="">All actions</option>
              {actions.map(([a, n]) => <option key={a} value={a}>{a} ({n})</option>)}
            </select>
            <button className="secondary sm" onClick={reload}>Refresh</button>
          </div>
          {loadError && <div className="card-body"><ErrorBox message={loadError} /></div>}
          <div className="table-wrap" style={{ maxHeight: 640 }}>
            <table>
              <thead>
                <tr>
                  <th className="num">#</th>
                  <th>Time (UTC)</th>
                  <th>Action</th>
                  <th>Subject</th>
                  <th>Actor</th>
                  <th>Hash</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((e) => (
                  <Fragment key={e.seq}>
                    <tr
                      className={`clickable ${open === e.seq ? "selected" : ""}`}
                      onClick={() => setOpen(open === e.seq ? null : e.seq)}
                      style={verify && !verify.valid && verify.broken_at === e.seq ? { background: "var(--red-100)" } : undefined}
                    >
                      <td className="num">{e.seq}</td>
                      <td className="small nowrap">{String(e.event_ts).replace("T", " ").slice(0, 19)}</td>
                      <td><code>{e.action_type}</code></td>
                      <td className="small"><code>{e.subject}</code></td>
                      <td className="small muted">{e.actor}</td>
                      <td className="hash" title={`prev ${e.prev_hash}`}>{e.row_hash.slice(0, 10)}…</td>
                    </tr>
                    {open === e.seq && (
                      <tr>
                        <td colSpan={6} style={{ background: "var(--surface-2)" }}>
                          <dl className="kv">
                            <dt>prev_hash</dt>
                            <dd className="hash">{e.prev_hash}</dd>
                            <dt>row_hash</dt>
                            <dd className="hash">{e.row_hash}</dd>
                          </dl>
                          <pre style={{ marginTop: 8 }}>{JSON.stringify(e.payload, null, 2)}</pre>
                          <button className="secondary sm" style={{ marginTop: 8 }} onClick={() => (setLineageId(e.subject), setLineageShown(e.subject))}>
                            Show lineage of {e.subject}
                          </button>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
            {events && shown.length === 0 && <div className="empty">No events match.</div>}
          </div>
        </div>

        <div className="card" style={{ position: "sticky", top: 72 }}>
          <div className="panel-title">Source lineage</div>
          <p className="small muted">Trace any artefact (edge, ask, sentence, fact, paper) back to its sources, with the agent, model and prompt hash at each step.</p>
          <form
            className="row"
            onSubmit={(ev) => {
              ev.preventDefault();
              setLineageShown(lineageId.trim() || null);
            }}
          >
            <input type="search" placeholder="EDG-…, ASK-…, SEN-…, FCT-…" value={lineageId} onChange={(e) => setLineageId(e.target.value)} style={{ flex: 1 }} />
            <button className="sm" type="submit">Trace</button>
          </form>
          <div style={{ marginTop: 12 }}>
            {lineageShown ? <LineageChain key={lineageShown} id={lineageShown} /> : <p className="tiny muted">Tip: open an event and click “Show lineage”.</p>}
          </div>
          <hr />
          <div className="panel-title">What the chain proves</div>
          <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
            <li>No event was edited or deleted since it was written.</li>
            <li>The order of events is the order they happened.</li>
            <li>Rejected edges and blocked queries are recorded too.</li>
          </ul>
          <div className="row" style={{ marginTop: 10 }}>
            <Status tone="info" label="sha256(prev | ts | actor | action | subject | payload)" />
          </div>
        </div>
      </div>
    </div>
  );
}
