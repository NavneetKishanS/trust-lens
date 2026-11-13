"use client";
import Link from "next/link";
import { useApi } from "@/lib/useApi";
import { isKgEdge, type AuditEvent, type Graph, type Health, type RareCase } from "@/lib/types";
import Status, { SyntheticFlag } from "@/components/Status";

const JOURNEY = [
  { text: "Open the literature graph around Moderna (CVX 207)", href: "/graph?concept=CVX:207&depth=2" },
  { text: "Select a contested relationship (amber)", href: "/graph?concept=&depth=1" },
  { text: "Read the verbatim quote and the source paper", href: "/graph?concept=CVX:207&depth=2" },
  { text: "Compare the literature verdict with the anonymised pool", href: "/graph?concept=CVX:213&depth=1" },
  { text: "Open Ask the Data", href: "/ask" },
  { text: "Ask the hypertension-after-Moderna question", href: "/ask?q=hypertension_after_moderna" },
  { text: "Inspect SQL, cohort results, suppressed cells and verdict", href: "/ask?q=hypertension_after_moderna" },
  { text: "Open the Cohort Explorer", href: "/cohorts" },
  { text: "Find the clinician-approved rare cases (e.g. blurred vision)", href: "/cohorts" },
  { text: "Verify the integrity of the audit chain", href: "/audit" },
];

function Metric({ k, v, d, tone }: { k: string; v: React.ReactNode; d?: string; tone: string }) {
  return (
    <div className={`metric ${tone}`}>
      <div className="k">{k}</div>
      <div className="v">{v}</div>
      {d && <div className="d">{d}</div>}
    </div>
  );
}

export default function Overview() {
  const { data: health } = useApi<Health>("/health");
  const { data: graph, error: graphErr } = useApi<Graph>("/research/graph?include_rejected=true");
  const { data: rare } = useApi<{ k: number; items: RareCase[] }>("/pool/rare");
  const { data: tpl } = useApi<{ templates: { key: string; question: string }[] }>("/research/ask/templates");
  const { data: audit } = useApi<AuditEvent[]>("/audit?limit=6");

  const rel = (graph?.edges ?? []).filter(isKgEdge);
  const accepted = rel.filter((e) => e.status === "ACCEPTED");
  const rejected = rel.filter((e) => e.status === "REJECTED");
  const contested = accepted.filter((e) => e.sanity.literature === "CONTESTED");
  const observed = accepted.filter((e) => e.sanity.pool === "OBSERVED");
  const cites = (graph?.edges ?? []).filter((e) => e.relation === "CITES").length;
  const dash = (v: number | null | undefined, ready: boolean) => (ready ? (v ?? "—") : <span className="skeleton" style={{ display: "inline-block", width: 48, height: 24 }} />);
  const hyp = tpl?.templates.find((t) => t.key === "hypertension_after_moderna");

  return (
    <div className="content">
      <section className="hero">
        <div>
          <div className="eyebrow" style={{ color: "var(--green-500)" }}>TrustLens Research Studio</div>
          <h1>Connect scientific literature, anonymised clinical data and verifiable AI.</h1>
          <p className="sub">
            Every relationship carries a verbatim quote and its paper. Every number in an answer comes from guarded SQL on an anonymised pool. Every step is in a
            hash-chained audit log.
          </p>
          <div className="row" style={{ marginTop: 14 }}>
            <Link className="btn primary" href="/graph?concept=CVX:207&depth=2">Start with the literature →</Link>
            <Link className="btn secondary" href="/audit" style={{ background: "transparent", color: "#d8e8ee", borderColor: "rgba(255,255,255,0.25)" }}>
              How we verify
            </Link>
          </div>
        </div>
        <div className="question">
          <div className="label">Suggested investigation</div>
          <div className="q">{hyp?.question ?? "Is hypertension onset more common after the Moderna vaccine in patients over 40?"}</div>
          <div className="row">
            <Link className="btn primary sm" href="/ask?q=hypertension_after_moderna">Run in Ask the Data</Link>
            <Link className="btn secondary sm" href="/graph?concept=CVX:213&depth=1" style={{ background: "transparent", color: "#d8e8ee", borderColor: "rgba(255,255,255,0.25)" }}>
              See the literature
            </Link>
          </div>
          <div className="row" style={{ marginTop: 10 }}>
            <SyntheticFlag label="Hypertension signal (PL2) is planted synthetic data" />
          </div>
        </div>
      </section>

      <div className="grid5" style={{ marginBottom: 18 }}>
        <Metric tone="navy" k="Papers indexed" v={dash(health?.counts.papers, !!health)} d={graph ? `${cites} citation links in this build` : "Europe PMC"} />
        <Metric tone="accent" k="Accepted relationships" v={dash(accepted.length, !!graph)} d={graph ? `${observed.length} also observed in the pool` : undefined} />
        <Metric tone="red" k="Rejected by A2 critic" v={dash(rejected.length, !!graph)} d="Kept for audit, hidden by default" />
        <Metric tone="amber" k="Contested in literature" v={dash(contested.length, !!graph)} d="Papers disagree on direction" />
        <Metric tone="accent" k="Validated rare-case groups" v={dash(rare?.items.length, !!rare)} d={rare ? `Clinician-approved · k = ${rare.k}` : undefined} />
      </div>
      {graphErr && <p className="small muted">Graph metrics unavailable: {graphErr}</p>}

      <div className="flow">
        <Link className="entry" href="/graph?concept=CVX:207&depth=2">
          <span className="step">A · Literature</span>
          <span className="title">Knowledge Graph</span>
          <span className="desc">What do papers say? Relationships with the exact quote, the paper, the critic result and whether other papers agree.</span>
          <span className="meta">{graph ? `${accepted.length} relationships · build ${graph.run_id ?? "—"}` : "…"}</span>
        </Link>
        <div className="arrow" aria-hidden>→</div>
        <Link className="entry" href="/ask">
          <span className="step">B · Clinical data</span>
          <span className="title">Ask the Data</span>
          <span className="desc">Is it visible in our anonymised pool? Plain-language questions become guarded SQL with suppressed small counts and a sufficiency verdict.</span>
          <span className="meta">{tpl ? `${tpl.templates.length} reviewed demo questions` : "…"}</span>
        </Link>
        <div className="arrow" aria-hidden>→</div>
        <Link className="entry" href="/cohorts">
          <span className="step">C · Validated cases</span>
          <span className="title">Cohort Explorer</span>
          <span className="desc">What are patients reporting that nobody expected? Rare cases enter the pool only after a clinician approves them.</span>
          <span className="meta">{rare ? `${rare.items.length} validated groups` : "…"}</span>
        </Link>
      </div>

      <div className="grid2">
        <div className="card">
          <h2>Guided investigation</h2>
          <p className="small muted">One connected path from a published claim to a verified, audited answer.</p>
          <ol className="journey">
            {JOURNEY.map((j) => (
              <li key={j.text}>
                <span className="small">{j.text}</span>
                <Link className="small" href={j.href}>Open →</Link>
              </li>
            ))}
          </ol>
        </div>
        <div className="stack" style={{ gap: 16 }}>
          <div className="card" style={{ marginBottom: 0 }}>
            <h2>How every answer earns trust</h2>
            <dl className="kv" style={{ gridTemplateColumns: "150px 1fr", gap: "8px 12px" }}>
              <dt>A1 Establisher</dt>
              <dd>Proposes a relationship and must quote one sentence from the abstract.</dd>
              <dt>A2 Critic</dt>
              <dd>Deterministic: quote verbatim, entities present, negation consistent. Fails are rejected, not hidden.</dd>
              <dt>A3 Sanity</dt>
              <dd>Other papers agree or contradict? Visible in the anonymised pool?</dd>
              <dt>SQL guard</dt>
              <dd>One read-only SELECT on pool.* views, aggregated, counts under 5 suppressed.</dd>
              <dt>Audit chain</dt>
              <dd>Every action hash-linked to the previous one; editing any row breaks the chain.</dd>
            </dl>
          </div>
          <div className="card" style={{ marginBottom: 0 }}>
            <div className="row">
              <h2 style={{ margin: 0 }}>Recent activity</h2>
              <span className="spacer" />
              <Link className="small" href="/audit">Trust & Audit →</Link>
            </div>
            <table style={{ marginTop: 8 }}>
              <tbody>
                {(audit ?? []).map((e) => (
                  <tr key={e.seq}>
                    <td className="num faint">#{e.seq}</td>
                    <td><code>{e.action_type}</code></td>
                    <td className="small muted">{e.subject}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {audit && audit.length === 0 && <p className="small muted">No events yet.</p>}
          </div>
          {health && (
            <div className="row small muted">
              <Status tone={health.db === "exasol" ? "ok" : "warn"} label={health.db === "exasol" ? "Exasol connected" : "Local DuckDB (not Exasol)"} />
              <Status tone={health.llm === "stub" ? "warn" : "ok"} label={health.llm === "stub" ? "AI agents in stub mode" : `AI: ${health.llm}`} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
