// Status is always colour + icon + text (never colour alone).
type Tone = "ok" | "warn" | "bad" | "info" | "muted";

const ICON: Record<Tone, string> = { ok: "✓", warn: "⚠", bad: "✕", info: "ℹ", muted: "?" };

const KNOWN: Record<string, [Tone, string]> = {
  // sentences / summaries
  verified: ["ok", "Verified"],
  needs_review: ["warn", "Needs review"],
  hidden_pending_review: ["muted", "Waiting for care team"],
  unverified: ["muted", "Unverified"],
  PASS: ["ok", "Critic pass"],
  FLAG: ["warn", "Critic flag"],
  FAIL: ["bad", "Critic fail"],
  SUPPORTED: ["ok", "Supported"],
  UNSUPPORTED: ["bad", "Unsupported"],
  UNSURE: ["warn", "Unsure"],
  // symptom classification / review
  EXPECTED: ["ok", "Expected side effect"],
  IN_RECORD: ["info", "Already in record"],
  NEW: ["warn", "New: clinician review"],
  UNMAPPED: ["warn", "Unmapped: clinician review"],
  pending: ["warn", "Pending review"],
  approved: ["ok", "Approved"],
  rejected: ["bad", "Rejected"],
  not_required: ["muted", "No review needed"],
  // research
  CONDITIONAL: ["warn", "Conditional"],
  NOT_SUPPORTED: ["bad", "Not supported"],
  ACCEPTED: ["ok", "Accepted"],
  REJECTED: ["bad", "Rejected"],
  CONSISTENT: ["ok", "Literature consistent"],
  CONTESTED: ["warn", "Literature contested"],
  SINGLE_SOURCE: ["muted", "Single source"],
  OBSERVED: ["info", "Seen in pool (synthetic)"],
  NOT_OBSERVED: ["muted", "Not seen in pool"],
  UNTESTABLE: ["muted", "Not testable in pool"],
  blocked: ["bad", "Blocked by guard"],
  guard_ok: ["ok", "Guard passed"],
};

export default function Status({ value, tone, label, title }: { value?: string | null; tone?: Tone; label?: string; title?: string }) {
  const known = value ? KNOWN[value] : undefined;
  const t: Tone = tone ?? known?.[0] ?? "muted";
  const text = label ?? known?.[1] ?? value ?? "Unknown";
  return (
    <span className={`status ${t}`} title={title}>
      <span aria-hidden>{ICON[t]}</span>
      {text}
    </span>
  );
}
