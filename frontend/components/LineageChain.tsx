"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Lineage, LineageStep } from "@/lib/types";
import ErrorBox from "./ErrorBox";

// Fetches GET /lineage/{id} (or uses a chain already in hand) and shows each upstream step.
export default function LineageChain({ id, chain }: { id: string; chain?: LineageStep[] }) {
  const [data, setData] = useState<Lineage | null>(chain ? { id, type: null, chain, producer: null } : null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (chain) return;
    let live = true;
    api<Lineage>(`/lineage/${encodeURIComponent(id)}`).then((r) => {
      if (!live) return;
      if (r.ok) setData(r.data);
      else setError(r.message);
    });
    return () => {
      live = false;
    };
  }, [id, chain]);

  if (error) return <ErrorBox message={`Lineage unavailable: ${error}`} />;
  if (!data) return <p className="muted small">Loading lineage…</p>;
  return (
    <div>
      {data.producer && (
        <p className="small">
          Produced by <b>{data.producer.agent}</b> · model <code>{data.producer.model}</code> · prompt{" "}
          <span className="hash">{data.producer.prompt_hash?.slice(0, 12)}</span>
        </p>
      )}
      {data.chain.length === 0 ? (
        <p className="muted small">No lineage recorded for {id}.</p>
      ) : (
        <ul className="chain">
          {data.chain.map((s, i) => (
            <li key={`${s.id}-${i}`} style={{ marginLeft: (s.depth - 1) * 14 }}>
              <div>
                <code>{s.id}</code> <span className="muted small">({s.type})</span>
              </div>
              <div className="small muted">
                {s.transform && <>transform <code>{s.transform}</code> </>}
                {s.agent && <>· agent <b>{s.agent}</b> </>}
                {s.model && <>· model <code>{s.model}</code> </>}
                {s.prompt_hash && <>· prompt <span className="hash">{s.prompt_hash.slice(0, 12)}</span></>}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
