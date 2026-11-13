"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import type { ReportResult } from "@/lib/types";
import ErrorBox from "./ErrorBox";
import Status from "./Status";

// POST /patients/{id}/reports → each extracted symptom with its deterministic classification.
export default function SymptomReport({ patientId }: { patientId: string }) {
  const [text, setText] = useState("Since my booster I'm tired, have a headache and blurred vision.");
  const [onset, setOnset] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ReportResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setBusy(true);
    const r = await api<ReportResult>(`/patients/${encodeURIComponent(patientId)}/reports`, {
      method: "POST",
      body: { text, onset_date: onset || null },
    });
    setBusy(false);
    if (r.ok) {
      setResult(r.data);
      setError(null);
    } else setError(r.message);
  }

  return (
    <div className="card">
      <h2>Tell your care team how you feel</h2>
      <p className="small muted">
        Known side effects are recorded for statistics. Anything unexpected is checked by a clinician before it is used.
      </p>
      <textarea value={text} onChange={(e) => setText(e.target.value)} />
      <div className="row" style={{ marginTop: 8 }}>
        <label className="small">
          Since when (optional) <input type="text" placeholder="YYYY-MM-DD" value={onset} onChange={(e) => setOnset(e.target.value)} size={12} />
        </label>
        <span className="spacer" />
        <button disabled={busy || !text.trim()} onClick={submit}>
          {busy ? "Sending…" : "Send report"}
        </button>
      </div>
      {error && <div style={{ marginTop: 10 }}><ErrorBox message={`Report not sent: ${error}`} /></div>}
      {result && (
        <div style={{ marginTop: 12 }}>
          <p className="small muted">
            Report <code>{result.report_id}</code> · audit #{result.audit_seq}
          </p>
          {result.urgent_advice && (
            <div className="urgent-banner" role="alert">
              <b>⚠ Please read this first</b>
              <p>{result.urgent_advice}</p>
            </div>
          )}
          {result.symptoms.length === 0 && <p className="muted">No symptoms recognised.</p>}
          {result.symptoms.map((s) => (
            <div key={s.symptom_id} className="edge">
              <div className="row">
                {s.urgent && <Status tone="bad" label="Urgent: sent to a clinician first" />}
                <b>“{s.span}”</b>
                <span className="muted">→ {s.term}</span>
                {s.snomed_code && <code className="small">SNOMED {s.snomed_code}</code>}
                <Status value={s.classification} />
                <Status value={s.review_status} />
              </div>
              <div className="small" style={{ marginTop: 4 }}>
                {s.reason}
              </div>
              {s.evidence.length > 0 && (
                <div className="small muted">
                  Evidence:{" "}
                  {s.evidence.map((e) =>
                    e.source_url ? (
                      <a key={e.id} href={e.source_url} target="_blank" rel="noreferrer" style={{ marginRight: 8 }}>
                        {e.id}
                      </a>
                    ) : (
                      <code key={e.id} style={{ marginRight: 8 }}>{e.id}</code>
                    ),
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
