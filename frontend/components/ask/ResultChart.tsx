// Horizontal bar chart of one returned column, by the first descriptive column. Values are the API's strings;
// "<5" and blank (suppressed) cells are drawn as hatched bars and never turned into numbers.
import type { AskResult } from "@/lib/types";

const isNum = (s: string) => s !== "" && s !== "<5" && Number.isFinite(Number(s));

export function pickChart(res: AskResult): { dim: number; metric: number } | null {
  if (!res.rows.length || res.rows.length > 30) return null;
  const cols = res.columns;
  const numericCol = (i: number) => res.rows.some((r) => isNum(r[i])) && res.rows.every((r) => isNum(r[i]) || r[i] === "" || r[i] === "<5");
  const dim = cols.findIndex((_, i) => !numericCol(i));
  if (dim < 0) return null;
  const pref = [/(rate|pct|percent)/i, /(avg|mean|median)/i, /^n_|count/i];
  for (const re of pref) {
    const m = cols.findIndex((c, i) => i !== dim && re.test(c) && numericCol(i) && !/window/i.test(c));
    if (m >= 0) return { dim, metric: m };
  }
  return null;
}

export default function ResultChart({ res, highlightRows }: { res: AskResult; highlightRows: Set<number> }) {
  const pick = pickChart(res);
  if (!pick) return null;
  const vals = res.rows.map((r) => (isNum(r[pick.metric]) ? Number(r[pick.metric]) : null));
  const max = Math.max(...vals.map((v) => v ?? 0), 1e-9);
  const metric = res.columns[pick.metric];
  const pct = /(rate|pct|percent)/i.test(metric);
  const countCol = res.columns.findIndex((c, i) => i !== pick.metric && /^n_/i.test(c));
  return (
    <div className="chart">
      <div className="row small muted" style={{ marginBottom: 6 }}>
        <span>
          <b className="strong" style={{ color: "var(--text)" }}>{metric}</b> by {res.columns[pick.dim]}
        </span>
        <span className="spacer" />
        <span>hatched = suppressed (k = 5)</span>
      </div>
      {res.rows.map((r, i) => {
        const v = vals[i];
        return (
          <div className="bar-row" key={i} style={highlightRows.has(i) ? { background: "var(--green-50)" } : undefined}>
            <span className="nowrap">{r[pick.dim]}</span>
            <span className="track">
              <span className={`fill ${v === null ? "suppressed" : ""}`} style={{ width: v === null ? "100%" : `${(v / max) * 100}%`, display: "block" }} />
            </span>
            <span className="val small">
              {v === null ? <i className="muted">suppressed</i> : `${r[pick.metric]}${pct ? "%" : ""}`}
              {countCol >= 0 && <span className="faint"> · n={r[countCol]}</span>}
            </span>
          </div>
        );
      })}
    </div>
  );
}
