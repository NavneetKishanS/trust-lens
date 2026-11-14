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
import Icon from "@/components/Icon";
import Term from "@/components/Term";

const VERDICT_TEXT: Record<string, string> = {
  SUPPORTED: "The data can answer this",
  CONDITIONAL: "The data can answer this, with caveats",
  NOT_SUPPORTED: "The data can't answer this reliably",
};

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
        sub={<>Ask a question in plain language. TrustLens answers from <Term k="pool">anonymised patient data</Term> and checks every number it shows you.</>}
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
              <span className="tiny muted">⌘/Ctrl + Enter to run · read-only, anonymised data only</span>
              <span className="spacer" />
              <button className="primary" disabled={busy || !question.trim()} onClick={() => ask(question)}>
                {busy ? <><span className="spinner" /> Working…</> : "Ask"}
              </button>
            </div>
          </div>

          {error && <div style={{ marginTop: 12 }}><ErrorBox message={error} /></div>}
          {!res && !busy && !error && (
            <div className="card" style={{ marginTop: 16 }}>
              <div className="empty">Pick an example question on the right, or write your own.</div>
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
              {/* 1. The answer, in plain words */}
              <div className="answer">
                <div className="verdict-line">
                  {res.guard.ok ? (
                    <>
                      <Status value={res.sufficiency.verdict} size="lg" />
                      <h2>{VERDICT_TEXT[res.sufficiency.verdict] ?? res.sufficiency.verdict}</h2>
                    </>
                  ) : (
                    <>
                      <Status value="blocked" size="lg" />
                      <h2>This request was refused for safety</h2>
                    </>
                  )}
                  {planted && <SyntheticFlag />}
                </div>

                {!res.guard.ok && (
                  <div className="guard-panel" style={{ marginTop: 10 }}>
                    <p className="small" style={{ margin: 0 }}>
                      The <Term k="guard">safety guard</Term> stopped this before any data was read. The refusal is still recorded in the audit log.
                    </p>
                    <ul className="small">{res.guard.violations.map((v) => <li key={v}>{v}</li>)}</ul>
                  </div>
                )}

                {res.summary.length > 0 && (
                  <section>
                    {res.summary.map((s, i) => (
                      <button
                        key={i}
                        className={`sentence ${s.status === "verified" ? "" : "warn"}`}
                        onMouseEnter={() => setHl(s.cells)}
                        onMouseLeave={() => setHl([])}
                        onFocus={() => setHl(s.cells)}
                        onBlur={() => setHl([])}
                      >
                        {s.text}
                        <span className="meta">
                          {s.cells.length ? <Status value={s.status} /> : <Status value="unverified" />}
                          {s.reasons && s.reasons.length > 0 && <span className="tiny">Check: {s.reasons.join("; ")}</span>}
                        </span>
                      </button>
                    ))}
                  </section>
                )}

                {causal && (
                  <div className="causation-banner" style={{ margin: "10px 0" }}>
                    <Icon name="alert" size={16} />
                    <span><b>Association only, not causation.</b> This shows a pattern in synthetic data, not that one thing causes the other.</span>
                  </div>
                )}

                {res.rows.length > 0 && (
                  <section style={{ margin: "14px 0 12px" }}>
                    <h3>Rate by group</h3>
                    <ResultChart res={res} highlightRows={hlRows} />
                    {res.suppressed_cells > 0 && (
                      <p className="tiny muted" style={{ marginTop: 6 }}>
                        Striped bars are <Term k="kanon">hidden for privacy</Term> (fewer than 5 patients).
                      </p>
                    )}
                  </section>
                )}
              </div>

              {/* 2. The proof, one click away */}
              <details className="proof" open={!res.guard.ok}>
                <summary>
                  How we know this
                  <span className="hint">data table, checks, exact query and audit trail</span>
                </summary>
                <div className="proof-body">
                  <div className="facts-strip" style={{ border: "1px solid var(--border)", borderRadius: "var(--radius-sm)" }}>
                    <div><div className="k">Patients (n)</div><div className="v">{res.guard.ok ? (res.sufficiency.n ?? "<5") : "—"}</div></div>
                    <div><div className="k">Result rows</div><div className="v">{res.rows.length}</div></div>
                    <div><div className="k">Hidden cells</div><div className="v">{res.suppressed_cells}</div></div>
                    <div><div className="k"><Term k="guard">Safety guard</Term></div><div className="v">{res.guard.ok ? "passed" : "blocked"}</div></div>
                    <div><div className="k">Method</div><div className="v">{res.mode === "template" ? "Reviewed template" : res.mode === "llm" ? "AI-written SQL" : "Researcher SQL"}</div></div>
                  </div>

                  {res.rows.length > 0 && (
                    <section>
                      <h3><Term k="sufficiency">Is the data enough?</Term></h3>
                      <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
                        {otherNotes.map((n) => <li key={n}>{n}</li>)}
                        {planted && <li>{notes.find((n) => /PL2|planted/i.test(n))}</li>}
                        {causal && <li>Association only, not causation</li>}
                      </ul>
                    </section>
                  )}

                  {res.rows.length > 0 && (
                    <section>
                      <h3>Result table <span className="muted small">· hover a sentence above to see which cells it cites</span></h3>
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
                      <summary>The exact query {res.guard.ok ? "that ran" : "that was refused"}</summary>
                      <pre>{res.sql}</pre>
                      {res.rationale && <p className="tiny muted" style={{ marginTop: 6 }}>AI rationale: {res.rationale}</p>}
                    </details>
                  )}

                  <details className="sql">
                    <summary><Term k="lineage">Lineage</Term>: which data and query produced this answer</summary>
                    <LineageChain id={res.ask_id} />
                  </details>

                  <p className="tiny muted" style={{ margin: 0 }}>
                    Answer ID <code>{res.ask_id}</code> · audit event #{res.audit_seq}
                  </p>
                </div>
              </details>
            </div>
          )}
        </div>

        <aside className="stack" style={{ gap: 16 }}>
          <div className="card" style={{ marginBottom: 0 }}>
            <div className="panel-title">Example questions</div>
            <div className="stack" style={{ gap: 6 }}>
              {(tpl?.templates ?? []).map((t) => (
                <button key={t.key} className="sentence" onClick={() => ask(t.question)} disabled={busy}>
                  <span className="small">{t.question}</span>
                </button>
              ))}
              {!tpl && <div className="skeleton" style={{ height: 90 }} />}
            </div>
            <details className="more">
              <summary>Test the safety guard</summary>
              <p className="small muted" style={{ margin: "6px 0" }}>Try a request that should be refused. Rules every query must pass:</p>
              <ul className="small" style={{ margin: "0 0 8px", paddingLeft: 18 }}>{GUARD_RULES.map((r) => <li key={r}>{r}</li>)}</ul>
              <div className="row">
                {UNSAFE_EXAMPLES.map((q) => (
                  <button key={q} className="chip danger" onClick={() => ask(q)} disabled={busy} title={q}>
                    {q.length > 38 ? q.slice(0, 38) + "…" : q}
                  </button>
                ))}
              </div>
            </details>
          </div>
          <div className="card" style={{ marginBottom: 0 }}>
            <div className="panel-title">Next</div>
            <div className="stack small">
              <Link href="/graph?concept=CVX:207">← What papers say about Moderna</Link>
              <Link href="/cohorts">New cases reported by patients →</Link>
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
