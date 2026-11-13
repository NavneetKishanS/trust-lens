"use client";
import { useMemo, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import type { AskResult, RareCase } from "@/lib/types";
import ErrorBox from "@/components/ErrorBox";
import PageHead from "@/components/PageHead";
import Status from "@/components/Status";

type Rare = { k: number; items: RareCase[] };
const uniq = (xs: string[]) => [...new Set(xs)].sort();

export default function CohortExplorer() {
  const { data, error, loading, reload } = useApi<Rare>("/pool/rare");
  const [search, setSearch] = useState("");
  const [exposure, setExposure] = useState("");
  const [sex, setSex] = useState("");
  const [band, setBand] = useState("");
  const [common, setCommon] = useState<AskResult | null>(null);
  const [commonBusy, setCommonBusy] = useState(false);
  const [commonErr, setCommonErr] = useState<string | null>(null);

  const items = useMemo(() => data?.items ?? [], [data]);
  const k = data?.k ?? 5;
  const filtered = items.filter(
    (r) =>
      (!search || `${r.term} ${r.exposure_label}`.toLowerCase().includes(search.toLowerCase())) &&
      (!exposure || r.exposure_label === exposure) &&
      (!sex || r.sex === sex) &&
      (!band || r.age_band === band),
  );
  const terms = uniq(items.map((r) => r.term));
  // "<5" is a suppressed value, never a number: only sum visible counts and say how many groups are suppressed
  const visibleSum = filtered.reduce((s, r) => s + (r.n_reports === "<5" ? 0 : Number(r.n_reports) || 0), 0);
  const suppressedGroups = filtered.filter((r) => r.n_reports === "<5").length;

  async function loadCommon() {
    setCommonBusy(true);
    setCommonErr(null);
    const r = await api<AskResult>("/research/ask", { method: "POST", body: { question: "What are the most common reported symptoms after vaccination?" } });
    setCommonBusy(false);
    if (r.ok) setCommon(r.data);
    else setCommonErr(r.message);
  }

  return (
    <div className="content">
      <PageHead
        eyebrow="Research · Anonymised pool"
        title="Cohort Explorer"
        sub="Clinician-validated rare cases: symptoms patients reported that were not a listed side effect and not already in their record, approved by a clinician before entering the research pool. Aggregates only; no patient identifiers."
        actions={<button className="secondary" onClick={reload}>Refresh</button>}
      />

      <div className="pathway">
        <div className="stage">
          <div className="n">1 · Patient report</div>
          <div className="t">Free-text symptom report</div>
          <div className="d">“Since my booster I’m tired, have a headache and blurred vision.”</div>
        </div>
        <div className="stage">
          <div className="n">2 · Deterministic classification</div>
          <div className="t row"><Status value="EXPECTED" /> <Status value="IN_RECORD" /></div>
          <div className="d">Recorded for statistics, no review needed. Anything else is <b>NEW</b>.</div>
        </div>
        <div className="stage">
          <div className="n">3 · Clinician approval</div>
          <div className="t row"><Status value="NEW" /></div>
          <div className="d">Waits in the <Link href="/review">Clinical Review</Link> queue until a clinician approves or rejects it.</div>
        </div>
        <div className="stage">
          <div className="n">4 · Validated rare-case pool</div>
          <div className="t">{items.length} group{items.length === 1 ? "" : "s"}</div>
          <div className="d">Approved NEW only. Counts under {k} are shown as &lt;{k}.</div>
        </div>
      </div>

      {error && <ErrorBox message={error} />}

      <div className="card flush">
        <div className="card-head">
          <h2>Validated rare cases</h2>
          <span className="hint">GET /pool/rare · k = {k}</span>
          <span className="spacer" />
          <input type="search" placeholder="Search symptom or exposure" value={search} onChange={(e) => setSearch(e.target.value)} />
          <select value={exposure} onChange={(e) => setExposure(e.target.value)}>
            <option value="">All exposures</option>
            {uniq(items.map((r) => r.exposure_label)).map((x) => <option key={x}>{x}</option>)}
          </select>
          <select value={band} onChange={(e) => setBand(e.target.value)}>
            <option value="">All ages</option>
            {uniq(items.map((r) => r.age_band)).map((x) => <option key={x}>{x}</option>)}
          </select>
          <select value={sex} onChange={(e) => setSex(e.target.value)}>
            <option value="">All sexes</option>
            {uniq(items.map((r) => r.sex)).map((x) => <option key={x}>{x}</option>)}
          </select>
        </div>
        <div className="card-body" style={{ paddingTop: 10 }}>
          <div className="row small" style={{ marginBottom: 10 }}>
            {terms.map((t) => (
              <button key={t} className="chip" onClick={() => setSearch(search === t ? "" : t)} style={search === t ? { background: "var(--navy-50)" } : undefined}>
                {t} · {items.filter((r) => r.term === t).length} group{items.filter((r) => r.term === t).length === 1 ? "" : "s"}
              </button>
            ))}
            <span className="spacer" />
            <span className="muted">
              Showing {filtered.length} of {items.length} groups
              {visibleSum > 0 && ` · ${visibleSum} reports in unsuppressed groups`}
              {suppressedGroups > 0 && ` · ${suppressedGroups} group${suppressedGroups === 1 ? "" : "s"} with <${k} reports`}
            </span>
          </div>
          {loading && !data && <div className="skeleton" style={{ height: 120 }} />}
          {data && items.length === 0 && (
            <div className="empty">No validated rare cases yet. They appear here after a clinician approves a NEW symptom in Clinical Review.</div>
          )}
          {filtered.length > 0 && (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Symptom</th>
                    <th>Classification</th>
                    <th>Exposure</th>
                    <th>Age band</th>
                    <th>Sex</th>
                    <th className="num">Reports</th>
                    <th>First observed</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((r, i) => (
                    <tr key={i}>
                      <td className="strong">{r.term}</td>
                      <td><Status tone="warn" label="NEW · clinician-approved" /></td>
                      <td>{r.exposure_label}</td>
                      <td>{r.age_band}</td>
                      <td>{r.sex}</td>
                      <td className={`num ${r.n_reports === "<5" ? "suppressed" : ""}`} title={r.n_reports === "<5" ? `Fewer than ${k}: suppressed` : undefined}>
                        {r.n_reports}
                      </td>
                      <td>{r.first_month}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      <div className="card flush">
        <div className="card-head">
          <h2>Context: all reported symptoms</h2>
          <span className="hint">EXPECTED, IN_RECORD and approved NEW, from pool.symptom_reports</span>
          <span className="spacer" />
          <button className="secondary sm" onClick={loadCommon} disabled={commonBusy}>
            {commonBusy ? "Running…" : common ? "Run again" : "Run guarded query"}
          </button>
        </div>
        <div className="card-body">
          {commonErr && <ErrorBox message={commonErr} />}
          {!common && !commonErr && (
            <p className="small muted" style={{ margin: 0 }}>
              Runs the “most common reported symptoms” question through Ask the Data (same guard and k-anonymity, audited), so rare cases can be read against the common, expected reactions.
            </p>
          )}
          {common && (
            <>
              <div className="row small" style={{ marginBottom: 8 }}>
                <Status value={common.sufficiency.verdict} />
                <span className="muted">{common.ask_id} · audit #{common.audit_seq}</span>
              </div>
              <table>
                <thead>
                  <tr>{common.columns.map((c) => <th key={c} className={/^n_/.test(c) ? "num" : undefined}>{c}</th>)}</tr>
                </thead>
                <tbody>
                  {common.rows.map((row, i) => (
                    <tr key={i}>
                      {row.map((cell, j) => (
                        <td key={j} className={`${/^n_/.test(common.columns[j]) ? "num" : ""} ${cell === "<5" ? "suppressed" : ""}`}>
                          {terms.includes(cell) ? <><b>{cell}</b> <Status tone="warn" label="also a rare case" /></> : cell}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
