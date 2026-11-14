import { GLOSSARY, type GlossaryKey } from "@/lib/glossary";

// A technical term with a plain-language explanation on hover or keyboard focus.
// The explanation is real text inside the element, so screen readers announce it too.
export default function Term({ k, children }: { k: GlossaryKey; children: React.ReactNode }) {
  return (
    <span className="term" tabIndex={0}>
      {children}
      <span className="term-tip" role="tooltip">
        {GLOSSARY[k]}
      </span>
    </span>
  );
}
