// Types copied from docs/context/00-shared.md §7 (API contract). Keep in sync with that file.

export type ApiError = { error: { code: string; message: string } };

// ---------------------------------------------------------------- system
export type Health = {
  status: string;
  db: "exasol" | "duckdb";
  llm: "bedrock" | "anthropic" | "stub";
  counts: { patients: number | null; papers: number | null; audit_events?: number | null };
  llm_region?: string | null;
  llm_eu_only?: boolean | null;
  db_location?: "local" | "remote" | null;
};

/** AI provider label from /health: names the real region and says "EU" only when the API confirms EU-only routing. */
export function llmLabel(h: Health): string {
  if (h.llm === "stub") return "stub mode";
  if (h.llm === "anthropic") return "Claude · Anthropic API";
  if (!h.llm_region) return "Claude · Bedrock";
  return `Claude · Bedrock ${h.llm_region}${h.llm_eu_only ? " (EU)" : ""}`;
}

/** Database label from /health: Exasol (local) vs Exasol (remote), DuckDB fallback. */
export function dbLabel(h: Health): string {
  if (h.db === "duckdb") return "DuckDB (local)";
  return h.db_location === "local" ? "Exasol (local)" : "Exasol";
}

// ---------------------------------------------------------------- clinical
export type PatientListItem = {
  patient_id: string;
  display_name: string;
  age: number;
  sex: string;
  last_encounter: string | null;
};

export type Fact = {
  fact_id: string;
  kind: string;
  data: Record<string, unknown>;
  source_row_ids: string[];
};

export type SentenceStatus = "verified" | "needs_review" | "hidden_pending_review";

export type Sentence = {
  sentence_id: string;
  text: string;
  fact_ids: string[];
  status: SentenceStatus;
  critic: { status: "PASS" | "FLAG"; reasons: string[] };
  verifier: { status: "SUPPORTED" | "UNSUPPORTED" | "UNSURE"; reason: string };
};

export type Summary = {
  summary_id: string;
  patient_id: string;
  audience: "patient" | "physician";
  overall_status: "verified" | "needs_review";
  sections: { title: string; sentences: Sentence[] }[];
  facts: Fact[];
  model: string;
  prompt_hash: string;
  audit_seq: number;
};

export type Evidence = { kind: string; id: string; source_url?: string };

export type Classification = "EXPECTED" | "IN_RECORD" | "NEW" | "UNMAPPED";

export type Symptom = {
  symptom_id: string;
  span: string;
  term: string;
  snomed_code: string | null;
  classification: Classification;
  reason: string;
  evidence: Evidence[];
  review_status: "not_required" | "pending" | "approved" | "rejected";
  urgent?: boolean;
};

export type ReportResult = {
  report_id: string;
  patient_id: string;
  symptoms: Symptom[];
  audit_seq: number;
  urgent?: boolean;
  urgent_advice?: string | null; // fixed safety text from the API, never LLM-written
};

// ---------------------------------------------------------------- oversight
export type ReviewItem = {
  item_id: string;
  kind: "symptom" | "sentence";
  patient_id: string;
  text: string;
  reason: string;
  evidence: Evidence[];
  created_at: string;
  priority?: "urgent" | "normal";
};

// ---------------------------------------------------------------- research
export type RareCase = {
  term: string;
  exposure_label: string;
  age_band: string;
  sex: string;
  n_reports: string;
  first_month: string;
};

export type Verdict = "SUPPORTED" | "CONDITIONAL" | "NOT_SUPPORTED";

export type AskResult = {
  ask_id: string;
  question: string;
  sql: string;
  guard: { ok: boolean; violations: string[] };
  columns: string[];
  rows: string[][];
  suppressed_cells: number;
  sufficiency: { verdict: Verdict; n: number | null; notes: string[] };
  summary: { text: string; cells: [number, string][]; status: "verified" | "needs_review"; reasons?: string[] }[];
  mode: "llm" | "template" | "sql";
  rationale?: string | null;
  template?: string | null;
  audit_seq: number;
};

export type PoolEvidence = {
  sql?: string;
  sql_source?: string;
  exposed_rate?: string | null;
  baseline_rate?: string | null;
  n_exposed?: string | null;
  n_unexposed?: string | null;
  n_outcome_exposed?: string | null;
  n_outcome_unexposed?: string | null;
  exposure_codes?: string[];
  synthetic?: boolean;
  note?: string;
  reason?: string;
};

export type GraphNode =
  | { node_id: string; type: "concept"; label: string; code_system: string; pool_patients: string | null; free?: boolean; known?: boolean }
  | { node_id: string; type: "paper"; label: string; year: number | null; url?: string };

export type KgEdge = {
  edge_id: string;
  src: string;
  dst: string;
  relation: string;
  quote: string;
  paper: { paper_id: string; doi: string | null; title: string | null; year: number | null; url: string };
  critic: { status: "PASS" | "FAIL"; reasons: string[] };
  sanity: {
    literature: "CONSISTENT" | "CONTESTED" | "SINGLE_SOURCE" | null;
    support_count: number | null;
    contradict_count: number | null;
    support_years?: { oldest: number; newest: number } | null;
    pool: "OBSERVED" | "NOT_OBSERVED" | "UNTESTABLE" | null;
    pool_evidence: PoolEvidence | null;
  };
  status: "ACCEPTED" | "REJECTED";
};

export type LinkEdge = { edge_id: string; src: string; dst: string; relation: "CITES" | "IS_A"; source?: string };

export type Graph = { run_id: string | null; nodes: GraphNode[]; edges: (KgEdge | LinkEdge)[] };

export type BuildResult = {
  run_id: string;
  papers: number;
  candidate_edges: number;
  accepted: number;
  rejected: number;
  audit_seq: number;
};

// ---------------------------------------------------------------- governance
export type LineageStep = {
  id: string;
  type: string;
  transform?: string | null;
  agent?: string | null;
  model?: string | null;
  prompt_hash?: string | null;
  depth: number;
};

export type Lineage = {
  id: string;
  type: string | null;
  chain: LineageStep[];
  producer: { agent: string; model: string; prompt_hash: string } | null;
};

export type AuditEvent = {
  seq: number;
  event_ts: string;
  actor: string;
  action_type: string;
  subject: string;
  payload: Record<string, unknown>;
  prev_hash: string;
  row_hash: string;
};

export type AuditVerify = { valid: boolean; length: number; broken_at: number | null };

export function isKgEdge(e: KgEdge | LinkEdge): e is KgEdge {
  return e.relation !== "CITES" && e.relation !== "IS_A";
}
