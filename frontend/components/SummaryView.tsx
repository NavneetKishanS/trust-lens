"use client";
import { useState } from "react";
import { useApi } from "@/lib/useApi";
import type { Fact, Sentence, Summary } from "@/lib/types";
import Drawer from "./Drawer";
import ErrorBox from "./ErrorBox";
import LineageChain from "./LineageChain";
import Status from "./Status";

function sentenceTone(s: Sentence): string {
  if (!s.fact_ids?.length) return "muted";
  if (s.status === "verified") return "";
  if (s.status === "hidden_pending_review") return "muted";
  return "warn";
}

// GET /patients/{id}/summary?audience=…  Every sentence is clickable: cited facts → source rows → lineage.
export default function SummaryView({ patientId, audience }: { patientId: string; audience: "patient" | "physician" }) {
  const [injectError, setInjectError] = useState(false);
  const [refreshes, setRefreshes] = useState(0);
  const [open, setOpen] = useState<Sentence | null>(null);

  const q = new URLSearchParams({ audience, inject_error: String(injectError) });
  if (refreshes > 0) q.set("refresh", "true");
  const path = `/patients/${encodeURIComponent(patientId)}/summary?${q}`;
  const { data: summary, error, loading, reload } = useApi<Summary>(path);
  const regenerate = () => (refreshes === 0 ? setRefreshes(1) : reload());

  const facts = new Map<string, Fact>((summary?.facts ?? []).map((f) => [f.fact_id, f]));

  return (
    <div>
      <div className="card row">
        {summary && <Status value={summary.overall_status} />}
        {summary && (
          <span className="small muted">
            model <code>{summary.model}</code> · prompt <span className="hash">{summary.prompt_hash?.slice(0, 12)}</span> · audit #
            {summary.audit_seq}
          </span>
        )}
        <span className="spacer" />
        {audience === "physician" && (
          <label className="row small" title="PL1: change one number in a lab sentence; the critic must flag it">
            <input type="checkbox" checked={injectError} onChange={(e) => setInjectError(e.target.checked)} /> inject_error (demo)
          </label>
        )}
        <button className="secondary" disabled={loading} onClick={regenerate}>
          {loading ? "Generating…" : "Regenerate"}
        </button>
      </div>

      {error && <ErrorBox message={`Summary unavailable: ${error}`} />}
      {!error && !summary && <p className="muted">Generating summary…</p>}

      {summary?.sections.map((sec) => (
        <div className="card" key={sec.title}>
          <h2>{sec.title}</h2>
          {sec.sentences.length === 0 && <p className="muted small">Nothing to report.</p>}
          {sec.sentences.map((s) => (
            <button key={s.sentence_id} className={`sentence ${sentenceTone(s)}`} onClick={() => setOpen(s)}>
              {s.text}
              <span className="meta">
                {s.fact_ids?.length ? <Status value={s.status} /> : <Status value="unverified" />}
                {audience === "physician" && s.critic && <Status value={s.critic.status} title={s.critic.reasons.join("; ")} />}
                {audience === "physician" && s.verifier && <Status value={s.verifier.status} title={s.verifier.reason} />}
                <span className="small muted">
                  {s.fact_ids?.length ? `${s.fact_ids.length} source fact${s.fact_ids.length > 1 ? "s" : ""} · click for lineage` : "no sources"}
                </span>
              </span>
            </button>
          ))}
        </div>
      ))}

      {open && (
        <Drawer title="Where this sentence comes from" onClose={() => setOpen(null)}>
          <p>{open.text}</p>
          <div className="row">
            <Status value={open.fact_ids?.length ? open.status : "unverified"} />
            {open.critic && <Status value={open.critic.status} />}
            {open.verifier && <Status value={open.verifier.status} />}
          </div>
          {open.critic?.reasons?.length > 0 && (
            <div className="notice small" style={{ marginTop: 8 }}>
              Critic: {open.critic.reasons.join("; ")}
            </div>
          )}
          {open.verifier?.reason && <p className="small muted">Verifier: {open.verifier.reason}</p>}
          <h3 style={{ marginTop: 14 }}>Cited facts (computed by SQL)</h3>
          {(open.fact_ids ?? []).map((fid) => {
            const f = facts.get(fid);
            return (
              <div key={fid} className="card" style={{ padding: 10 }}>
                <div className="row">
                  <code>{fid}</code> <span className="small muted">{f?.kind}</span>
                </div>
                {f ? (
                  <>
                    <pre>{JSON.stringify(f.data, null, 2)}</pre>
                    <div className="small">
                      Source rows: {f.source_row_ids.map((r) => <code key={r} style={{ marginRight: 6 }}>{r}</code>)}
                    </div>
                  </>
                ) : (
                  <p className="small muted">Fact not included in this response.</p>
                )}
              </div>
            );
          })}
          <h3 style={{ marginTop: 14 }}>Lineage</h3>
          <LineageChain id={open.sentence_id} />
        </Drawer>
      )}
    </div>
  );
}
