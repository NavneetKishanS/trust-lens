"use client";
import { useApi } from "@/lib/useApi";
import type { RareCase } from "@/lib/types";
import ErrorBox from "./ErrorBox";

// GET /pool/rare: clinician-validated NEW symptoms, counts under k shown as "<5".
export default function RarePanel() {
  const { data, error, reload: load } = useApi<{ k: number; items: RareCase[] }>("/pool/rare");
  const items = data?.items ?? null;
  const k = data?.k ?? 5;

  return (
    <div className="card">
      <div className="row">
        <h2>Validated rare cases</h2>
        <span className="spacer" />
        <button className="secondary" onClick={load}>
          Refresh
        </button>
      </div>
      <p className="small muted">Patient-reported symptoms a clinician approved as new. Counts under {k} are shown as &lt;{k}.</p>
      {error && <ErrorBox message={error} />}
      {items && items.length === 0 && <p className="muted">No validated rare cases yet.</p>}
      {items && items.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Symptom</th>
              <th>After</th>
              <th>Age band</th>
              <th>Sex</th>
              <th>Reports</th>
              <th>First seen</th>
            </tr>
          </thead>
          <tbody>
            {items.map((r, i) => (
              <tr key={i}>
                <td>{r.term}</td>
                <td>{r.exposure_label}</td>
                <td>{r.age_band}</td>
                <td>{r.sex}</td>
                <td className={`num ${r.n_reports === "<5" ? "suppressed" : ""}`}>{r.n_reports}</td>
                <td>{r.first_month}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
