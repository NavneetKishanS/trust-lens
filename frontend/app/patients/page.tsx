"use client";
import Link from "next/link";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { useApi } from "@/lib/useApi";
import type { PatientListItem } from "@/lib/types";
import ErrorBox from "@/components/ErrorBox";
import PageHead from "@/components/PageHead";

export default function PatientsPage() {
  const [vaccinated, setVaccinated] = useState(false);
  const [manual, setManual] = useState("");
  const router = useRouter();
  const { data: patients, error, loading } = useApi<PatientListItem[]>(`/patients?limit=50${vaccinated ? "&vaccinated=true" : ""}`);

  return (
    <div className="content">
      <PageHead
        eyebrow="Clinical views"
        title="Patient & physician views"
        sub="The same evidence-backed engine, for one synthetic patient at a time: a plain-language patient summary and a coded physician summary, every sentence traced to its source rows."
      />
      <div className="card flush">
        <div className="card-head">
          <h2>Synthetic patients</h2>
          <span className="hint">GET /patients</span>
          <span className="spacer" />
          <label className="check"><input type="checkbox" checked={vaccinated} onChange={(e) => setVaccinated(e.target.checked)} /> vaccinated only</label>
          <input type="search" placeholder="Patient ID" value={manual} onChange={(e) => setManual(e.target.value)} />
          <button className="secondary sm" disabled={!manual.trim()} onClick={() => router.push(`/patient/${manual.trim()}`)}>Patient view</button>
          <button className="secondary sm" disabled={!manual.trim()} onClick={() => router.push(`/physician/${manual.trim()}`)}>Physician view</button>
        </div>
        <div className="card-body">
          {error && <ErrorBox message={`Patient list unavailable: ${error}`} />}
          {loading && !patients && <div className="skeleton" style={{ height: 80 }} />}
          {patients && patients.length === 0 && <div className="empty">No patients returned.</div>}
          {patients && patients.length > 0 && (
            <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Name (synthetic)</th>
                  <th className="num">Age</th>
                  <th>Sex</th>
                  <th>Last encounter</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {patients.map((p) => (
                  <tr key={p.patient_id}>
                    <td className="strong">{p.display_name}</td>
                    <td className="num">{p.age}</td>
                    <td>{p.sex}</td>
                    <td>{p.last_encounter ?? "—"}</td>
                    <td className="row" style={{ justifyContent: "flex-end" }}>
                      <Link className="btn secondary sm" href={`/patient/${p.patient_id}`}>Patient view</Link>
                      <Link className="btn secondary sm" href={`/physician/${p.patient_id}`}>Physician view</Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
