// Plain-language explanations for the project's technical terms, shown by <Term> on hover / focus.
// Keep each one to a sentence a first-time viewer understands without other context.
export const GLOSSARY = {
  a1: "The AI agent that reads paper abstracts and proposes a relationship, quoting the exact sentence it relied on.",
  a2: "An automatic, rule-based check (not AI) that the quote really appears in the paper and says what is claimed. Fails are rejected, not hidden.",
  a3: "A cross-check: do other papers agree or disagree, and does the pattern also show up in our anonymised patient data?",
  pool: "A de-identified copy of the patient data that researchers can query. No names, no IDs, only aggregated counts.",
  kanon: "Privacy rule: any count below 5 patients is hidden (shown as “<5”), so no small group can be re-identified.",
  guard: "A safety check that runs before any query: read-only, anonymised tables only, results must be aggregated.",
  sufficiency: "Whether the data is enough to answer the question: Supported, Conditional (usable with caveats) or Not supported.",
  lineage: "The trail from an answer back to the exact data, query and documents that produced it.",
  audit: "Every action is logged and linked to the previous one by a hash, so editing any past entry is detectable.",
  planted: "A deliberately inserted fake pattern used to prove the system can find signals. Not a finding about any real vaccine.",
  cvx: "CVX is the standard US code list for vaccines. CVX 207 is the Moderna COVID-19 vaccine.",
  contested: "Some papers in the collection report the opposite of this relationship.",
  rareCase: "A symptom patients reported that is not a known side effect, which a clinician reviewed and approved for research.",
} as const;

export type GlossaryKey = keyof typeof GLOSSARY;
