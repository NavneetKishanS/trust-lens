"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Health } from "@/lib/types";

export default function HealthBadge() {
  const [h, setH] = useState<Health | null>(null);
  const [down, setDown] = useState(false);
  useEffect(() => {
    api<Health>("/health").then((r) => (r.ok ? setH(r.data) : setDown(true)));
  }, []);
  if (down) return <span>✕ API offline</span>;
  if (!h) return <span>…</span>;
  return (
    <span title="GET /health">
      ✓ API · db {h.db} · llm {h.llm}
      {h.llm === "stub" && " (stub mode)"}
    </span>
  );
}
