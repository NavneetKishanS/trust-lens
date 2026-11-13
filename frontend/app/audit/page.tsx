"use client";
import { Fragment, useState } from "react";
import { useApi } from "@/lib/useApi";
import { api } from "@/lib/api";
import type { AuditEvent, AuditVerify } from "@/lib/types";
import ErrorBox from "@/components/ErrorBox";
import Status from "@/components/Status";

export default function AuditPage() {
  const { data: events, error: loadError, reload: load } = useApi<AuditEvent[]>("/audit?limit=100");
  const [verifyError, setError] = useState<string | null>(null);
  const error = verifyError ?? loadError;
  const [verify, setVerify] = useState<AuditVerify | null>(null);
  const [checking, setChecking] = useState(false);
  const [open, setOpen] = useState<number | null>(null);

  async function runVerify() {
    setChecking(true);
    const r = await api<AuditVerify>("/audit/verify");
    setChecking(false);
    if (r.ok) setVerify(r.data);
    else setError(r.message);
  }

  return (
    <>
      <h1>Audit log</h1>
      <p className="sub">
        Every action is appended to a hash chain: each row&apos;s hash covers the previous hash and its own content, so editing any
        row breaks every hash after it.
      </p>
      <div className="card row">
        <button onClick={runVerify} disabled={checking}>
          {checking ? "Recomputing…" : "Verify chain"}
        </button>
        {verify &&
          (verify.valid ? (
            <Status tone="ok" label={`Chain valid · ${verify.length} events recomputed`} />
          ) : (
            <Status tone="bad" label={`Chain broken at #${verify.broken_at} (of ${verify.length})`} />
          ))}
        <span className="spacer" />
        <button className="secondary" onClick={load}>
          Refresh
        </button>
      </div>
      {error && <ErrorBox message={`Audit log unavailable: ${error}`} />}
      {events && (
        <div className="card">
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Time (UTC)</th>
                <th>Actor</th>
                <th>Action</th>
                <th>Subject</th>
                <th>Hash</th>
              </tr>
            </thead>
            <tbody>
              {events.map((e) => (
                <Fragment key={e.seq}>
                  <tr
                    onClick={() => setOpen(open === e.seq ? null : e.seq)}
                    style={{ cursor: "pointer", background: verify && !verify.valid && verify.broken_at === e.seq ? "#fbe3e2" : undefined }}
                  >
                    <td className="num">{e.seq}</td>
                    <td className="small">{e.event_ts.replace("T", " ").slice(0, 19)}</td>
                    <td className="small">{e.actor}</td>
                    <td>
                      <code>{e.action_type}</code>
                    </td>
                    <td className="small">
                      <code>{e.subject}</code>
                    </td>
                    <td className="hash" title={`prev ${e.prev_hash}`}>
                      {e.row_hash.slice(0, 12)}…
                    </td>
                  </tr>
                  {open === e.seq && (
                    <tr>
                      <td colSpan={6}>
                        <div className="small hash">prev_hash {e.prev_hash}</div>
                        <div className="small hash">row_hash {e.row_hash}</div>
                        <pre>{JSON.stringify(e.payload, null, 2)}</pre>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
