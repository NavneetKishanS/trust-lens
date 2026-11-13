"use client";
import { usePathname } from "next/navigation";
import { useApi } from "@/lib/useApi";
import type { Health } from "@/lib/types";
import { crumbsFor } from "./nav";

// Connection status comes straight from GET /health: never claims Exasol when the API reports DuckDB.
export default function Topbar() {
  const path = usePathname() ?? "/";
  const { section, page } = crumbsFor(path);
  const { data: h, error } = useApi<Health>("/health");
  return (
    <header className="topbar">
      <div className="crumbs">
        <span>{section}</span>
        {page && (
          <>
            <span aria-hidden>›</span>
            <b>{page}</b>
          </>
        )}
      </div>
      <span className="workspace" title="Research topic of the current knowledge graph build">
        <span className="dot" />
        Workspace: COVID-19 vaccine safety
      </span>
      <div className="right">
        {error && (
          <span className="conn bad" title={error}>
            <span className="led" /> API offline
          </span>
        )}
        {h && (
          <>
            <span className={`conn ${h.db === "exasol" ? "ok" : "warn"}`} title="Database the API is connected to (GET /health)">
              <span className="led" /> Database <b>{h.db === "exasol" ? "Exasol" : "DuckDB (local)"}</b>
            </span>
            <span className={`conn ${h.llm === "stub" ? "warn" : "ok"}`} title="LLM provider used by the agents (GET /health)">
              <span className="led" /> AI{" "}
              <b>{h.llm === "stub" ? "stub mode" : h.llm === "bedrock" ? "Claude · Bedrock EU" : "Claude · Anthropic API"}</b>
            </span>
          </>
        )}
        {!h && !error && (
          <span className="conn">
            <span className="led" /> connecting…
          </span>
        )}
      </div>
    </header>
  );
}
