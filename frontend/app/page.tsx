"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { PatientListItem } from "@/lib/types";
import ErrorBox from "@/components/ErrorBox";

export default function Home() {
  const [patients, setPatients] = useState<PatientListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [vaccinated, setVaccinated] = useState(true);
  const [manual, setManual] = useState("");
  const router = useRouter();

  useEffect(() => {
    let live = true;
    api<PatientListItem[]>(`/patients?limit=20${vaccinated ? "&vaccinated=true" : ""}`).then((r) => {
      if (!live) return;
      if (r.ok) {
        setPatients(r.data);
        setError(null);
      } else setError(r.message);
    });
    return () => {
      live = false;
    };
  }, [vaccinated]);

  return (
    <>
      <h1>Patients</h1>
      <p className="sub">Synthetic patients (Synthea). Open the patient view or the physician view of the same record.</p>

      <div className="card">
        <div className="row">
          <label className="row small">
            <input type="checkbox" checked={vaccinated} onChange={(e) => setVaccinated(e.target.checked)} /> vaccinated only
          </label>
          <span className="spacer" />
          <input type="text" placeholder="Patient ID (UUID)" value={manual} onChange={(e) => setManual(e.target.value)} size={38} />
          <button className="secondary" disabled={!manual.trim()} onClick={() => router.push(`/patient/${manual.trim()}`)}>
            Patient view
          </button>
          <button className="secondary" disabled={!manual.trim()} onClick={() => router.push(`/physician/${manual.trim()}`)}>
            Physician view
          </button>
        </div>
      </div>

      <div className="card">
        {error && <ErrorBox message={`Patient list unavailable: ${error}`} />}
        {!error && !patients && <p className="muted">Loading…</p>}
        {patients && patients.length === 0 && <p className="muted">No patients returned.</p>}
        {patients && patients.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Name (synthetic)</th>
                <th>Age</th>
                <th>Sex</th>
                <th>Last encounter</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {patients.map((p) => (
                <tr key={p.patient_id}>
                  <td>{p.display_name}</td>
                  <td>{p.age}</td>
                  <td>{p.sex}</td>
                  <td>{p.last_encounter ?? "—"}</td>
                  <td className="row">
                    <Link href={`/patient/${p.patient_id}`}>Patient view</Link>
                    <Link href={`/physician/${p.patient_id}`}>Physician view</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
