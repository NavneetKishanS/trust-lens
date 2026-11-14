"use client";
import Link from "next/link";
import { useApi } from "@/lib/useApi";
import { isKgEdge, type AuditEvent, type Graph, type Health, type RareCase } from "@/lib/types";
import Status, { SyntheticFlag } from "@/components/Status";
import Icon from "@/components/Icon";
import Term from "@/components/Term";

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
  const dash = (v: number | null | undefined, ready: boolean) => (ready ? (v ?? "—") : <span className="skeleton" style={{ display: "inline-block", width: 32, height: 16 }} />);
  const hyp = tpl?.templates.find((t) => t.key === "hypertension_after_moderna");

  return (
    <div className="content">
      <section className="hero">
        <div>
          <div className="eyebrow on-dark">TrustLens Research Studio</div>
          <h1>Find out what research says, and check it against real patient data.</h1>
          <p className="sub">
            TrustLens reads published papers, compares their claims with anonymised clinical data, and shows its proof for every answer.
          </p>
          <div className="row" style={{ marginTop: 16 }}>
            <Link className="btn primary" href="/graph?concept=CVX:207&depth=2">Start the 3-step tour →</Link>
            <Link className="btn on-dark" href="/audit">How we verify</Link>
          </div>
        </div>
        <div className="question">
          <div className="label">Example question</div>
          <div className="q">{hyp?.question ?? "Is hypertension onset more common after the Moderna vaccine in patients over 40?"}</div>
          <div className="row">
            <Link className="btn primary sm" href="/ask?q=hypertension_after_moderna">See the answer</Link>
          </div>
          <div className="row" style={{ marginTop: 10 }}>
            <SyntheticFlag label="Uses a planted test signal, not a real finding" />
          </div>
        </div>
      </section>

      <h2 style={{ marginBottom: 12 }}>How it works</h2>
      <div className="steps3">
        <Link className="entry" href="/graph?concept=CVX:207&depth=2">
          <span className="step">Literature</span>
          <span className="title">What do papers say?</span>
          <span className="desc">A map of relationships found in published papers. Each one links to the exact sentence it came from.</span>
          <span className="meta">Open the Knowledge Graph →</span>
        </Link>
        <Link className="entry" href="/ask?q=hypertension_after_moderna">
          <span className="step">Patient data</span>
          <span className="title">Does our data show it too?</span>
          <span className="desc">Ask a question in plain language. TrustLens answers from anonymised records and hides any group smaller than 5 patients.</span>
          <span className="meta">Open Ask the Data →</span>
        </Link>
        <Link className="entry" href="/cohorts">
          <span className="step">New cases</span>
          <span className="title">What are patients reporting?</span>
          <span className="desc">Unexpected symptoms reported by patients, added to research only after a clinician approves them.</span>
          <span className="meta">Open the Cohort Explorer →</span>
        </Link>
      </div>

      <div className="stat-strip" aria-label="Current numbers">
        <span><b>{dash(health?.counts.papers, !!health)}</b>papers read</span>
        <span><b>{dash(accepted.length, !!graph)}</b>relationships passed the quote check</span>
        <span><b>{dash(rejected.length, !!graph)}</b>rejected (kept for audit)</span>
        <span><b>{dash(contested.length, !!graph)}</b>where papers disagree</span>
        <span><b>{dash(rare?.items.length, !!rare)}</b>clinician-approved rare-case groups</span>
      </div>
      {graphErr && <p className="small muted">Graph numbers unavailable: {graphErr}</p>}

      <div className="grid2">
        <div className="card">
          <h2>Why you can trust the answers</h2>
          <ul className="trust-list">
            <li><span className="ic"><Icon name="check" size={15} /></span><span>Every claim from a paper comes with the <b>exact quoted sentence</b>, checked word for word by an automatic <Term k="a2">quote check</Term>.</span></li>
            <li><span className="ic"><Icon name="shield" size={15} /></span><span>Questions only run on <Term k="pool">anonymised data</Term>, and <Term k="kanon">groups under 5 patients are hidden</Term>.</span></li>
            <li><span className="ic"><Icon name="info" size={15} /></span><span>Every number in an AI summary is <b>matched to the result table</b>; anything unchecked is labelled.</span></li>
            <li><span className="ic"><Icon name="alert" size={15} /></span><span>Answers say <b>&ldquo;association, not causation&rdquo;</b>: the data shows patterns, not proof of cause.</span></li>
            <li><span className="ic"><Icon name="review" size={15} /></span><span>Every step is written to a <Term k="audit">tamper-evident log</Term> you can verify in one click.</span></li>
          </ul>
        </div>
        <div className="stack" style={{ gap: 16 }}>
          <div className="card" style={{ marginBottom: 0 }}>
            <div className="row">
              <h2 style={{ margin: 0 }}>Recent activity</h2>
              <span className="spacer" />
              <Link className="small" href="/audit">Full log →</Link>
            </div>
            <table style={{ marginTop: 8 }}>
              <tbody>
                {(audit ?? []).slice(0, 4).map((e) => (
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
          <div className="card" style={{ marginBottom: 0 }}>
            <details className="more" style={{ borderTop: "none", marginTop: 0, paddingTop: 0 }}>
              <summary>Presenter script: the full 10-step demo</summary>
              <ol className="journey" style={{ marginTop: 8 }}>
                {JOURNEY.map((j) => (
                  <li key={j.text}>
                    <span className="small">{j.text}</span>
                    <Link className="small" href={j.href}>Open →</Link>
                  </li>
                ))}
              </ol>
            </details>
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
