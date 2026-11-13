"use client";
import { Suspense, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import type { AskResult } from "@/lib/types";
import ErrorBox from "@/components/ErrorBox";
import LineageChain from "@/components/LineageChain";
import PageHead from "@/components/PageHead";
import Status, { SyntheticFlag } from "@/components/Status";
import ResultChart from "@/components/ask/ResultChart";

type Templates = { templates: { key: string; question: string }[] };

const UNSAFE_EXAMPLES = [
  "List the names and birth dates of patients who got the Moderna vaccine",
  "Show me the raw rows of pool.observations for every patient",
  "DELETE FROM pool.patients",
  "SELECT display_name, COUNT(*) AS n FROM curated.patients GROUP BY display_name",
];

const GUARD_RULES = [
  "Exactly one read-only SELECT; no writes or DDL",
  "Only the anonymised pool.* views",
  "Results must be aggregated, with a count column",
  "No patient identifiers in the output",
  "Whitelisted functions only; LIMIT 1000",
  "Counts under 5 suppressed (k-anonymity)",
];

function AskWorkbench() {
  const params = useSearchParams();
  const initial = params.get("q");
  const { data: tpl } = useApi<Templates>("/research/ask/templates");
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(Boolean(initial));
  const [res, setRes] = useState<AskResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hl, setHl] = useState<[number, string][]>([]);
  const autoRan = useRef(false);

  // ?q=<template key or question> runs once, after the templates have loaded
  useEffect(() => {
    if (!initial || autoRan.current || (!tpl && !initial.includes(" "))) return;
    autoRan.current = true;
    const q = tpl?.templates.find((t) => t.key === initial)?.question ?? initial;
    api<AskResult>("/research/ask", { method: "POST", body: { question: q } }).then((r) => {
      setQuestion(q);
      setBusy(false);
      if (r.ok) setRes(r.data);
      else setError(r.message);
    });
  }, [initial, tpl]);

  async function ask(q: string) {
    if (!q.trim()) return;
    setQuestion(q);
    setBusy(true);
    setHl([]);
    setError(null);
    const r = await api<AskResult>("/research/ask", { method: "POST", body: { question: q } });
    setBusy(false);
    if (r.ok) setRes(r.data);
    else setError(r.message);
  }

  const isHl = (ri: number, col: string) => hl.some(([r, c]) => r === ri && c === col);
  const hlRows = new Set(hl.map(([r]) => r));
  const notes = res?.sufficiency.notes ?? [];
  const causal = Boolean(res?.guard.ok) && notes.some((n) => /association only/i.test(n));
  const planted = notes.some((n) => /PL2|planted/i.test(n));
  const otherNotes = notes.filter((n) => !/association only/i.test(n) && !/PL2|planted/i.test(n));

  return (
    <div className="content">
      <PageHead
        eyebrow="Research · Anonymised pool"
        title="Ask the Data"
        sub="Ask a research question in plain language. TrustLens turns it into guarded SQL over the anonymised pool only, suppresses small counts, and checks every number in the summary against the result table."
      />

      <div className="workbench">
        <div>
          <div className="query-box">
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="e.g. Is hypertension onset more common after the Moderna vaccine in patients over 40?"
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) ask(question);
              }}
            />
            <div className="bar">
              <span className="tiny muted">⌘/Ctrl + Enter to run · read-only · pool.* only</span>
              <span className="spacer" />
              <button className="primary" disabled={busy || !question.trim()} onClick={() => ask(question)}>
                {busy ? <><span className="spinner" /> Running…</> : "Run query"}
              </button>
            </div>
          </div>

          {error && <div style={{ marginTop: 12 }}><ErrorBox message={error} /></div>}
          {!res && !busy && !error && (
            <div className="card" style={{ marginTop: 16 }}>
              <div className="empty">Pick a suggested question on the right, or write your own.</div>
            </div>
          )}
          {busy && !res && (
            <div className="card" style={{ marginTop: 16 }}>
              <div className="skeleton" style={{ height: 16, width: "40%" }} />
              <div className="skeleton" style={{ height: 120, marginTop: 12 }} />
            </div>
          )}

          {res && (
            <div className="card flush" style={{ marginTop: 16, opacity: busy ? 0.55 : 1 }}>
              <div className="result-head">
                <Status value={res.sufficiency.verdict} size="lg" />
                {res.guard.ok ? <Status value="guard_ok" /> : <Status value="blocked" />}
                <Status tone="info" label={res.mode === "template" ? "Demo template" : res.mode === "llm" ? "LLM text-to-SQL" : "Researcher SQL"} />
                {planted && <SyntheticFlag />}
                <span className="spacer" />
                <span className="tiny muted">
                  <code>{res.ask_id}</code> · audit event #{res.audit_seq}
                </span>
              </div>
              <div className="facts-strip">
                <div><div className="k">Verdict</div><div className="v">{res.sufficiency.verdict.replace("_", " ").toLowerCase()}</div></div>
                <div><div className="k">Patients / records (n)</div><div className="v">{res.guard.ok ? (res.sufficiency.n ?? "<5") : "—"}</div></div>
                <div><div className="k">Result rows</div><div className="v">{res.rows.length}</div></div>
                <div><div className="k">Suppressed cells</div><div className="v">{res.suppressed_cells}</div></div>
                <div><div className="k">Query guard</div><div className="v">{res.guard.ok ? "passed" : "blocked"}</div></div>
              </div>

              <div className="card-body stack" style={{ gap: 14 }}>
                {causal && (
                  <div className="causation-banner">
                    <span aria-hidden>⚠</span>
                    <span><b>Association only, not causation.</b> Observational, synthetic data. Nothing here shows that an exposure causes an outcome.</span>
                  </div>
                )}

                {!res.guard.ok && (
                  <div className="guard-panel">
                    <div className="strong">Query blocked before anything ran</div>
                    <p className="small" style={{ margin: "4px 0 0" }}>The SQL guard refused this request. No data was read and the refusal is in the audit log (ask.blocked).</p>
                    <ul className="small">{res.guard.violations.map((v) => <li key={v}>{v}</li>)}</ul>
                  </div>
                )}

                {res.summary.length > 0 && (
                  <section>
                    <h3>Research summary · each sentence cites result cells</h3>
                    {res.summary.map((s, i) => (
                      <button
                        key={i}
                        className={`sentence ${s.status === "verified" ? "" : "warn"}`}
                        onMouseEnter={() => setHl(s.cells)}
                        onMouseLeave={() => setHl([])}
                        onFocus={() => setHl(s.cells)}
                      >
                        {s.text}
                        <span className="meta">
                          {s.cells.length ? <Status value={s.status} /> : <Status value="unverified" />}
                          <span className="tiny muted">{s.cells.length} cited cell{s.cells.length === 1 ? "" : "s"} · hover to highlight</span>
                          {s.reasons && s.reasons.length > 0 && <span className="tiny">Critic: {s.reasons.join("; ")}</span>}
                        </span>
                      </button>
                    ))}
                  </section>
                )}

                {res.rows.length > 0 && (
                  <section className="grid2" style={{ alignItems: "start" }}>
                    <div>
                      <h3>Cohort comparison</h3>
                      <ResultChart res={res} highlightRows={hlRows} />
                    </div>
                    <div>
                      <h3>Sufficiency assessment</h3>
                      <div className="row" style={{ marginBottom: 6 }}><Status value={res.sufficiency.verdict} /></div>
                      <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
                        {otherNotes.map((n) => <li key={n}>{n}</li>)}
                        {planted && <li>{notes.find((n) => /PL2|planted/i.test(n))}</li>}
                        {causal && <li>Association only, not causation</li>}
                      </ul>
                    </div>
                  </section>
                )}

                {res.rows.length > 0 && (
                  <section>
                    <h3>Result table · k-anonymised</h3>
                    <div className="table-wrap">
                      <table>
                        <thead>
                          <tr>
                            <th className="num">#</th>
                            {res.columns.map((c) => <th key={c}>{c}</th>)}
                          </tr>
                        </thead>
                        <tbody>
                          {res.rows.map((row, ri) => (
                            <tr key={ri}>
                              <td className="num faint">{ri}</td>
                              {row.map((cell, ci) => (
                                <td
                                  key={ci}
                                  className={`${isHl(ri, res.columns[ci]) ? "hl" : ""} ${cell === "<5" || cell === "" ? "suppressed" : ""}`}
                                  title={cell === "<5" ? "Fewer than 5: suppressed" : cell === "" ? "Suppressed (computed from a count under 5)" : undefined}
                                >
                                  {cell === "" ? "—" : cell}
                                </td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </section>
                )}

                {res.sql && (
                  <details className="sql" open={!res.guard.ok}>
                    <summary>SQL inspector · {res.guard.ok ? "the exact query that ran (after the guard added LIMIT)" : "the query that was refused"}</summary>
                    <pre>{res.sql}</pre>
                    {res.rationale && <p className="tiny muted" style={{ marginTop: 6 }}>LLM rationale: {res.rationale}</p>}
                  </details>
                )}

                <details className="sql">
                  <summary>Lineage · which pool views and SQL produced this answer</summary>
                  <LineageChain id={res.ask_id} />
                </details>
              </div>
            </div>
          )}
        </div>

        <aside className="stack" style={{ gap: 16 }}>
          <div className="card" style={{ marginBottom: 0 }}>
            <div className="panel-title">Suggested research questions</div>
            <div className="stack" style={{ gap: 6 }}>
              {(tpl?.templates ?? []).map((t) => (
                <button key={t.key} className="sentence" onClick={() => ask(t.question)} disabled={busy}>
                  <span className="small">{t.question}</span>
                </button>
              ))}
              {!tpl && <div className="skeleton" style={{ height: 90 }} />}
            </div>
            <p className="tiny muted" style={{ marginTop: 8 }}>These run as reviewed demo templates and work without an LLM. Other questions use LLM text-to-SQL when an LLM is connected.</p>
          </div>
          <div className="card" style={{ marginBottom: 0 }}>
            <div className="panel-title">Query guard</div>
            <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>{GUARD_RULES.map((r) => <li key={r}>{r}</li>)}</ul>
            <div className="panel-title" style={{ marginTop: 12 }}>Try an unsafe request</div>
            <div className="row">
              {UNSAFE_EXAMPLES.map((q) => (
                <button key={q} className="chip danger" onClick={() => ask(q)} disabled={busy} title={q}>
                  {q.length > 38 ? q.slice(0, 38) + "…" : q}
                </button>
              ))}
            </div>
          </div>
          <div className="card" style={{ marginBottom: 0 }}>
            <div className="panel-title">Continue the investigation</div>
            <div className="stack small">
              <Link href="/graph?concept=CVX:207">← Literature around Moderna (Knowledge Graph)</Link>
              <Link href="/cohorts">Validated rare cases (Cohort Explorer) →</Link>
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}

export default function AskPage() {
  return (
    <Suspense fallback={<div className="content">Loading…</div>}>
      <AskWorkbench />
    </Suspense>
  );
}
