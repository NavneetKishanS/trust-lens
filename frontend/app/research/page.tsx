import AskPanel from "@/components/AskPanel";
import GraphPanel from "@/components/GraphPanel";
import RarePanel from "@/components/RarePanel";

export default function ResearchPage() {
  return (
    <>
      <h1>Researcher</h1>
      <p className="sub">
        Anonymised, synthetic patient pool (no names, no exact dates, small counts suppressed) and a knowledge graph of research
        papers from Europe PMC. The hypertension signal after Moderna in the pool is <b>planted synthetic data</b>, not a finding
        about real vaccines.
      </p>
      <AskPanel />
      <RarePanel />
      <GraphPanel />
    </>
  );
}
