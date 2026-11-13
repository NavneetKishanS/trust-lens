"use client";
import { useState } from "react";
import { useApi } from "@/lib/useApi";
import { api } from "@/lib/api";
import type { ReviewItem } from "@/lib/types";
import ErrorBox from "@/components/ErrorBox";
import Status from "@/components/Status";

export default function ReviewPage() {
  const { data, error: loadError, reload: load } = useApi<{ items: ReviewItem[] }>("/review/queue");
  const items = data?.items ?? null;
  const [decideError, setError] = useState<string | null>(null);
  const error = decideError ?? loadError;
  const [reviewer, setReviewer] = useState("Dr. Weber");
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [done, setDone] = useState<Record<string, string>>({});

  async function decide(item: ReviewItem, decision: "approve" | "reject") {
    const r = await api<{ ok: boolean; audit_seq: number }>(`/review/${encodeURIComponent(item.item_id)}`, {
      method: "POST",
      body: { decision, reviewer, note: notes[item.item_id] ?? "" },
    });
    if (r.ok) setDone((d) => ({ ...d, [item.item_id]: `${decision === "approve" ? "Approved" : "Rejected"} · audit #${r.data.audit_seq}` }));
    else setError(r.message);
  }

  return (
    <>
      <h1>Clinician review queue</h1>
      <p className="sub">Flagged summary sentences and new patient-reported symptoms. Approved new symptoms become validated rare cases in the research pool.</p>
      <div className="card row">
        <label className="small">
          Reviewer <input type="text" value={reviewer} onChange={(e) => setReviewer(e.target.value)} />
        </label>
        <span className="spacer" />
        <button className="secondary" onClick={load}>
          Refresh
        </button>
      </div>
      {error && <ErrorBox message={`Review queue unavailable: ${error}`} />}
      {items && items.length === 0 && <p className="muted">Nothing waiting for review.</p>}
      {items?.map((it) => (
        <div className="card" key={it.item_id}>
          <div className="row">
            <Status tone={it.kind === "symptom" ? "warn" : "info"} label={it.kind === "symptom" ? "Patient symptom" : "Summary sentence"} />
            <code className="small">{it.item_id}</code>
            <span className="small muted">patient {it.patient_id.slice(0, 8)}… · {it.created_at}</span>
          </div>
          <p style={{ margin: "8px 0" }}>“{it.text}”</p>
          <div className="notice small">Why: {it.reason}</div>
          {it.evidence?.length > 0 && (
            <p className="small muted">
              Evidence: {it.evidence.map((e) => <code key={e.id} style={{ marginRight: 6 }}>{e.id}</code>)}
            </p>
          )}
          {done[it.item_id] ? (
            <p>
              <Status value={done[it.item_id].startsWith("Approved") ? "approved" : "rejected"} label={done[it.item_id]} />
            </p>
          ) : (
            <div className="row" style={{ marginTop: 8 }}>
              <input
                type="text"
                placeholder="Note (optional)"
                value={notes[it.item_id] ?? ""}
                onChange={(e) => setNotes((n) => ({ ...n, [it.item_id]: e.target.value }))}
                style={{ flex: 1 }}
              />
              <button className="approve" disabled={!reviewer.trim()} onClick={() => decide(it, "approve")}>
                ✓ Approve
              </button>
              <button className="reject" disabled={!reviewer.trim()} onClick={() => decide(it, "reject")}>
                ✕ Reject
              </button>
            </div>
          )}
        </div>
      ))}
    </>
  );
}
