// Status is always colour + icon + text (never colour alone). Each known value carries a plain-language tooltip.
type Tone = "ok" | "warn" | "bad" | "info" | "muted";

const ICON: Record<Tone, string> = { ok: "✓", warn: "⚠", bad: "✕", info: "◆", muted: "○" };

const KNOWN: Record<string, [Tone, string, string?]> = {
  // sentences / summaries
  verified: ["ok", "Verified", "Every number checked against cited data"],
  needs_review: ["warn", "Needs review", "A check failed; a human must look at it"],
  hidden_pending_review: ["muted", "Waiting for care team"],
  unverified: ["muted", "Unverified", "No sources cited"],
  PASS: ["ok", "Critic pass", "A2 deterministic checks passed"],
  FLAG: ["warn", "Critic flag"],
  FAIL: ["bad", "Critic fail", "A2 deterministic checks failed"],
  SUPPORTED: ["ok", "Supported", "The data is sufficient for this question"],
  UNSUPPORTED: ["bad", "Unsupported"],
  UNSURE: ["warn", "Unsure"],
  // symptom classification / review
  EXPECTED: ["ok", "Expected side effect", "Listed effect of a product the patient received, within its window"],
  IN_RECORD: ["info", "Already in record", "Documented by the doctor in the last 365 days"],
  NEW: ["warn", "New: clinician review"],
  UNMAPPED: ["warn", "Unmapped: clinician review"],
  pending: ["warn", "Pending review"],
  approved: ["ok", "Approved"],
  rejected: ["bad", "Rejected"],
  not_required: ["muted", "No review needed"],
  // research
  CONDITIONAL: ["warn", "Conditional", "Usable with the listed limitations"],
  NOT_SUPPORTED: ["bad", "Not supported", "The data cannot answer this question"],
  ACCEPTED: ["ok", "Accepted", "Passed the A2 critic"],
  REJECTED: ["bad", "Rejected", "Failed the A2 critic; kept for audit"],
  CONSISTENT: ["ok", "Consistent", "Other papers in the corpus report the same direction"],
  CONTESTED: ["warn", "Contested", "Other papers in the corpus report the opposite"],
  SINGLE_SOURCE: ["muted", "Single source", "No other paper in the corpus reports this pair"],
  OBSERVED: ["info", "Observed in pool", "Exposed rate above baseline in the synthetic pool (n ≥ 20)"],
  NOT_OBSERVED: ["muted", "Not observed in pool", "Exposed rate not above baseline in the synthetic pool"],
  UNTESTABLE: ["muted", "Untestable in pool", "Concept not in the pool, or too few patients"],
  blocked: ["bad", "Blocked by guard", "Refused before any SQL ran"],
  guard_ok: ["ok", "Guard passed", "One read-only SELECT on pool.* only"],
};

export default function Status({
  value,
  tone,
  label,
  title,
  size,
}: {
  value?: string | null;
  tone?: Tone;
  label?: string;
  title?: string;
  size?: "lg";
}) {
  const known = value ? KNOWN[value] : undefined;
  const t: Tone = tone ?? known?.[0] ?? "muted";
  const text = label ?? known?.[1] ?? value ?? "Unknown";
  return (
    <span className={`status ${t} ${size ?? ""}`} title={title ?? known?.[2]}>
      <span aria-hidden>{ICON[t]}</span>
      {text}
    </span>
  );
}

export function SyntheticFlag({ label = "Planted synthetic signal" }: { label?: string }) {
  return (
    <span className="synthetic-flag" title="Deliberately planted test data (origin='seed_signal' / dev pool). Not a finding about any real vaccine.">
      ◇ {label}
    </span>
  );
}
