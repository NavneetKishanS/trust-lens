// Shared vocabulary for the knowledge graph screens: relation wording, colours, filters.
import type { GraphNode, KgEdge } from "./types";

export const RELATION_TEXT: Record<string, string> = {
  ASSOCIATED_WITH: "is associated with",
  INCREASES_RISK_OF: "increases risk of",
  DECREASES_RISK_OF: "decreases risk of",
  ADVERSE_EVENT_OF: "is an adverse event of",
  TREATS: "treats",
  NO_ASSOCIATION_WITH: "has no association with",
  CITES: "cites",
  IS_A: "is a",
};

export const RELATION_LABEL: Record<string, string> = {
  ASSOCIATED_WITH: "Associated with",
  INCREASES_RISK_OF: "Increases risk of",
  DECREASES_RISK_OF: "Decreases risk of",
  ADVERSE_EVENT_OF: "Adverse event of",
  TREATS: "Treats",
  NO_ASSOCIATION_WITH: "No association",
};

export const LIT_COLOR: Record<string, string> = {
  CONSISTENT: "#3f9a2a",
  CONTESTED: "#d39a1f",
  SINGLE_SOURCE: "#8a9ba4",
};
export const REJECTED_COLOR = "#c9504a";

export const SYSTEM_COLOR: Record<string, string> = {
  CVX: "#134e64",
  RXNORM: "#1f6680",
  SNOMED: "#2c8a76",
  LOINC: "#a3741c",
  FREE: "#a9b6bd",
};

export const SYSTEM_LABEL: Record<string, string> = {
  CVX: "Vaccine (CVX)",
  RXNORM: "Medication (RxNorm)",
  SNOMED: "Condition (SNOMED CT)",
  LOINC: "Lab test (LOINC)",
  FREE: "Uncoded concept",
};

export function edgeColor(e: KgEdge): string {
  if (e.status === "REJECTED") return REJECTED_COLOR;
  return LIT_COLOR[e.sanity.literature ?? "SINGLE_SOURCE"] ?? LIT_COLOR.SINGLE_SOURCE;
}

export function nodeSystem(n: GraphNode): string {
  if (n.type === "paper") return "PAPER";
  if (n.free || n.node_id.startsWith("FREE:")) return "FREE";
  return n.code_system;
}

export function shortLabel(label: string, max = 34): string {
  const clean = label
    .replace(/^SARS-COV-2 mRNA vaccine \((.+)\)$/i, "$1 vaccine")
    .replace(/^SARS-COV-2 vaccine \((.+)\)$/i, "$1 vaccine")
    .replace(/\s*\((disorder|finding)\)$/i, "");
  return clean.length > max ? clean.slice(0, max - 1) + "…" : clean;
}

export const SUGGESTED_CONCEPTS = [
  { id: "CVX:207", label: "Moderna (CVX 207)" },
  { id: "CVX:208", label: "Pfizer-BioNTech (CVX 208)" },
  { id: "CVX:213", label: "COVID-19 vaccine (any)" },
  { id: "SNOMED:59621000", label: "Hypertension" },
];
