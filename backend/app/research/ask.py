"""Ask the data (Dev C §5): question → SQL → guard → run read-only → k-anonymity → sufficiency → cited summary.

Paths, in order:
1. SQL mode: the researcher sent SQL (body `sql`, or the question itself is SQL). Same guard, nothing else.
2. Question pre-check: refuse identity / raw-row / write requests before any SQL exists.
3. Template: 5 demo questions with hand-written SQL (keyword match). Works in stub mode.
4. LLM text-to-SQL (prompts/ask_sql.md, effort medium).
The guard runs before every execution, whatever produced the SQL.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from decimal import Decimal

from pydantic import BaseModel

from app.research import deps, guard, store

ACTOR = "research.ask"
K = 5
MIN_N = 20
TIMEOUT_S = 20
ASSOCIATION_NOTE = "Association only, not causation"
PL2_NOTE = "Includes the planted synthetic signal PL2 (origin='seed_signal'); not a finding about real vaccines"
CAUSAL = re.compile(r"\b(causes?|caused|causing|leads? to|led to|results? in|resulted in|proves?|proven|"
                    r"because of|due to)\b", re.I)
_ASSOC_Q = re.compile(r"\b(after|more common|less common|risk|associat\w*|linked|link|compare\w*|vs\.?|versus|"
                      r"higher|lower|increase\w*|decrease\w*|effect)\b", re.I)


# ---------------------------------------------------------------------------------------- templates

T_HYPERTENSION_MODERNA = """
WITH first_dose AS (
  SELECT pseudo_id, MIN(imm_month) AS imm_month
  FROM pool.immunizations WHERE concept_code = '207' GROUP BY pseudo_id
),
dose AS (
  SELECT f.pseudo_id, MIN(i.age_band_at_dose) AS age_band,
         CAST(SUBSTR(f.imm_month, 1, 4) AS INTEGER) * 12 + CAST(SUBSTR(f.imm_month, 6, 2) AS INTEGER) AS m
  FROM first_dose f
  JOIN pool.immunizations i ON i.pseudo_id = f.pseudo_id AND i.imm_month = f.imm_month AND i.concept_code = '207'
  GROUP BY f.pseudo_id, f.imm_month
),
onset AS (
  SELECT pseudo_id, CAST(SUBSTR(onset_month, 1, 4) AS INTEGER) * 12 + CAST(SUBSTR(onset_month, 6, 2) AS INTEGER) AS m
  FROM pool.conditions WHERE concept_code = '59621000'
)
SELECT d.age_band,
       COUNT(DISTINCT d.pseudo_id) AS n_exposed,
       COUNT(DISTINCT CASE WHEN o.m BETWEEN d.m AND d.m + 3 THEN d.pseudo_id END) AS n_hypertension,
       ROUND(100.0 * COUNT(DISTINCT CASE WHEN o.m BETWEEN d.m AND d.m + 3 THEN d.pseudo_id END)
             / COUNT(DISTINCT d.pseudo_id), 1) AS rate_pct,
       3 AS window_months
FROM dose d LEFT JOIN onset o ON o.pseudo_id = d.pseudo_id
GROUP BY d.age_band
ORDER BY d.age_band
"""

T_COMMON_SYMPTOMS = """
SELECT term, COUNT(*) AS n_reports, COUNT(DISTINCT pseudo_id) AS n_patients
FROM pool.symptom_reports
WHERE exposure_code IS NOT NULL
GROUP BY term
ORDER BY n_reports DESC, term
LIMIT 10
"""

T_RARE = """
SELECT term, exposure_label, age_band, sex, n_reports, first_month
FROM pool.rare_cases
ORDER BY first_month DESC, term
"""

T_HBA1C_AGE = """
SELECT p.age_band, COUNT(DISTINCT o.pseudo_id) AS n_patients, ROUND(AVG(o.value_num), 1) AS avg_hba1c_pct
FROM pool.observations o JOIN pool.patients p ON p.pseudo_id = o.pseudo_id
WHERE o.concept_code = '4548-4' AND o.value_num IS NOT NULL
GROUP BY p.age_band
ORDER BY p.age_band
"""

T_METFORMIN_SEX = """
SELECT p.sex, COUNT(DISTINCT m.pseudo_id) AS n_patients
FROM pool.medications m JOIN pool.patients p ON p.pseudo_id = m.pseudo_id
WHERE LOWER(m.description) LIKE '%metformin%'
GROUP BY p.sex
ORDER BY p.sex
"""


@dataclass
class Template:
    key: str
    example: str
    keywords: list[list[str]]  # every group must match (any word in the group)
    sql: str
    sentence: str  # format string over column names
    pick: str = "first"  # first | extremes:<column>
    association: bool = False
    notes: tuple[str, ...] = ()


TEMPLATES = [
    Template("hypertension_after_moderna", "Is hypertension onset more common after the Moderna vaccine in patients over 40?",
             [["hypertension", "high blood pressure"], ["moderna", "mrna-1273", "spikevax", "cvx 207", "cvx:207"]],
             T_HYPERTENSION_MODERNA,
             "Among patients aged {age_band} at their first Moderna dose, {rate_pct}% had a hypertension onset "
             "within {window_months} months ({n_hypertension} of {n_exposed}).",
             pick="extremes:rate_pct", association=True, notes=(PL2_NOTE,)),
    Template("rare_validated_symptoms", "Which rare symptoms have clinicians validated?",
             [["rare"]], T_RARE,
             "{term} after {exposure_label}: {n_reports} clinician-validated reports (age band {age_band}, sex {sex}), "
             "first in {first_month}."),
    Template("common_symptoms_after_vaccination", "What are the most common reported symptoms after vaccination?",
             [["symptom", "side effect", "reported"], ["common", "frequent", "top", "most"]], T_COMMON_SYMPTOMS,
             "{term} was reported {n_reports} times by {n_patients} patients."),
    Template("hba1c_by_age_band", "What is the average HbA1c by age band?",
             [["hba1c", "a1c", "hemoglobin a1c", "glycated"], ["average", "mean", "avg", "age"]], T_HBA1C_AGE,
             "Patients aged {age_band} had an average HbA1c of {avg_hba1c_pct}% ({n_patients} patients).",
             pick="extremes:avg_hba1c_pct"),
    Template("metformin_by_sex", "How many patients are on metformin, by sex?",
             [["metformin"]], T_METFORMIN_SEX,
             "{n_patients} patients of sex {sex} have a metformin prescription."),
]


def match_template(question: str) -> Template | None:
    q = question.lower()
    for t in TEMPLATES:
        if all(any(w in q for w in group) for group in t.keywords):
            return t
    return None


# --------------------------------------------------------------------------------------- LLM models


class SqlDraft(BaseModel):
    sql: str
    rationale: str


class CellRef(BaseModel):
    row: int
    column: str


class SummarySentence(BaseModel):
    text: str
    cells: list[CellRef]


class SummaryDraft(BaseModel):
    sentences: list[SummarySentence]


FALLBACK_POOL_SCHEMA = """\
pool.patients(pseudo_id, age_band, sex, race, ethnicity)                       -- age_band = 10-year band, e.g. '40-49'
pool.conditions(pseudo_id, concept_code, description, onset_month, age_band_at_onset)   -- SNOMED CT codes
pool.observations(pseudo_id, concept_code, description, value_num, units, obs_month)    -- LOINC codes
pool.medications(pseudo_id, concept_code, description, start_month, stop_month)         -- RxNorm codes
pool.immunizations(pseudo_id, concept_code, description, imm_month, age_band_at_dose)   -- CVX codes
pool.symptom_reports(pseudo_id, term, classification, exposure_code, exposure_label, days_since_exposure, report_month)
pool.rare_cases(term, exposure_label, age_band, sex, n_reports, first_month)            -- already aggregated
All *_month columns are 'YYYY-MM' strings. pseudo_id is the only patient key."""


def pool_schema_text() -> str:
    path = deps.REPO_ROOT / "db" / "pool_schema.md"
    return path.read_text() if path.exists() else FALLBACK_POOL_SCHEMA


# ----------------------------------------------------------------------------------- k-anon + format


def _num(v) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float, Decimal)):
        return float(v)
    try:
        return float(str(v))
    except (TypeError, ValueError):
        return None


def _fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return str(round(v, 4))
    return str(v)


def kind_of(col: str, kinds: dict[str, str]) -> str:
    if col in kinds:
        return kinds[col]
    return guard.classify_name(col)


def anonymise(columns: list[str], raw_rows: list[list], kinds: dict[str, str]) -> tuple[list[list[str]], int]:
    """Counts < k → "<5"; other aggregates in the same row → "" (blank). Returns (string rows, suppressed cells)."""
    out, suppressed = [], 0
    col_kinds = [kind_of(c, kinds) for c in columns]
    for raw in raw_rows:
        row = [_fmt(v) for v in raw]
        small = [i for i, (k, v) in enumerate(zip(col_kinds, raw)) if k == "count" and _num(v) is not None
                 and _num(v) < K]
        if small:
            for i in small:
                row[i] = "<5"
                suppressed += 1
            for i, k in enumerate(col_kinds):
                if k == "aggregate" and row[i] != "":
                    row[i] = ""
                    suppressed += 1
        out.append(row)
    return out, suppressed


# ------------------------------------------------------------------------------------- sufficiency


def sufficiency(columns: list[str], raw_rows: list[list], kinds: dict[str, str], suppressed: int,
                association: bool, extra_notes=()) -> dict:
    notes = [ASSOCIATION_NOTE]
    count_cols = [i for i, c in enumerate(columns) if kind_of(c, kinds) == "count"]
    if count_cols:
        n = int(sum(_num(r[count_cols[0]]) or 0 for r in raw_rows))
    else:
        n = len(raw_rows)
        notes.append("No count column; n is the number of rows")
    if suppressed:
        notes.append(f"{suppressed} cells under k={K} suppressed")
    notes += list(extra_notes)
    n_out = n if n >= K else None  # never return a count under k as a number
    if n < MIN_N:
        notes.append(f"Fewer than {MIN_N} patients/records in total" + ("" if n_out is not None else " (fewer than 5)"))
        return dict(verdict="NOT_SUPPORTED", n=n_out, notes=notes)
    if association:
        notes.append("Observational data without a matched comparison group")
    verdict = "CONDITIONAL" if suppressed or association else "SUPPORTED"
    return dict(verdict=verdict, n=n_out, notes=notes)


# ------------------------------------------------------------------------------------ summary + critic

_SAFE_SMALL = re.compile(r"(fewer than 5|less than 5|under 5|<\s*5|k\s*=\s*5)", re.I)
_NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?")


def _cell_numbers(cell: str) -> list[float]:
    if cell.strip() == "<5":
        return []
    return [float(x) for x in _NUMBER.findall(cell)]


def critic(text: str, cells: list[list], columns: list[str], rows: list[list[str]]) -> list[str]:
    reasons = []
    allowed: list[float] = []
    for ref in cells:
        r, c = ref
        if not (isinstance(r, int) and 0 <= r < len(rows)) or c not in columns:
            reasons.append(f"cited cell {ref} does not exist")
            continue
        allowed += _cell_numbers(rows[r][columns.index(c)])
    for tok in _NUMBER.findall(_SAFE_SMALL.sub(" ", text)):
        if not any(abs(float(tok) - a) <= 0.1 for a in allowed):
            reasons.append(f"number {tok} is not in a cited cell")
    m = CAUSAL.search(text)
    if m:
        reasons.append(f"causal wording {m.group(0)!r}")
    return reasons


def _pick_rows(rows: list[list[str]], columns: list[str], pick: str) -> list[int]:
    clean = [i for i, r in enumerate(rows) if "<5" not in r and "" not in r]
    if pick.startswith("extremes:") and pick.split(":", 1)[1] in columns:
        ci = columns.index(pick.split(":", 1)[1])
        vals = [(float(rows[i][ci]), i) for i in clean if _num(rows[i][ci]) is not None]
        if len(vals) >= 2:
            hi, lo = max(vals)[1], min(vals)[1]
            return sorted({hi, lo})
    return (clean or list(range(len(rows))))[:3]


def stub_summary(columns: list[str], rows: list[list[str]], template: Template | None) -> list[dict]:
    out = []
    if not rows:
        return out
    for i in _pick_rows(rows, columns, template.pick if template else "first"):
        row = rows[i]
        vals = {c: ("fewer than 5" if v == "<5" else v) for c, v in zip(columns, row)}
        if template:
            text = template.sentence.format(**vals)
            used = [c for c in columns if "{" + c + "}" in template.sentence]
        else:
            dims = [f"{v}" for c, v in vals.items() if not c.startswith(("n_", "count")) and _num(v) is None and v]
            rest = [f"{c} {v}" for c, v in vals.items() if (c.startswith(("n_", "count")) or _num(v) is not None) and v]
            text = (", ".join(dims) + ": " if dims else f"Row {i + 1}: ") + ", ".join(rest) + "."
            used = [c for c, v in vals.items() if v]
        out.append(dict(text=text, cells=[[i, c] for c in used]))
    return out


def summarise(columns, rows, template) -> tuple[list[dict], dict]:
    if not rows:
        return [], dict(model=None, prompt_hash=None, ok=True)
    if deps.llm_provider() == "stub" or template is not None:
        # templates have hand-written sentences; the LLM summary is the path for new questions
        return stub_summary(columns, rows, template), dict(model="stub" if template is None else "template",
                                                           prompt_hash=None, ok=True)
    parsed, meta = deps.llm_call("ask_summary", "ask_summary.md",
                                 dict(columns=columns, rows=rows[:50]), SummaryDraft, effort="low")
    if parsed is None:
        return [dict(text="The AI summary is unavailable; read the table directly.", cells=[], llm_failed=True)], meta
    return [dict(text=s.text, cells=[[c.row, c.column] for c in s.cells]) for s in parsed.sentences[:3]], meta


# ----------------------------------------------------------------------------------------- pipeline


def _run(db, sql: str) -> list[dict]:
    ex = ThreadPoolExecutor(max_workers=1)
    fut = ex.submit(db.query, sql)
    try:
        return fut.result(timeout=TIMEOUT_S)
    except FutureTimeout:
        if hasattr(db, "interrupt"):
            db.interrupt()
        raise TimeoutError(f"query exceeded {TIMEOUT_S}s")
    finally:
        ex.shutdown(wait=False)


def ask(question: str, sql: str | None = None, db=None) -> dict:
    db = db or deps.get_db()
    store.ensure_schema(db)
    question = (question or "").strip()
    ask_id = store.run_id("ASK")
    dialect = getattr(db, "dialect", "duckdb")
    template, llm_meta, rationale = None, dict(model=None, prompt_hash=None), None
    violations: list[str] = []

    if sql and sql.strip():
        mode, proposed = "sql", sql.strip()
    elif guard.SQL_START.match(question):
        mode, proposed = "sql", question
    else:
        violations = guard.check_question(question)
        template = None if violations else match_template(question)
        if violations:
            mode, proposed = "template", ""
        elif template:
            mode, proposed = "template", template.sql.strip()
        else:
            mode = "llm"
            if deps.llm_provider() == "stub":
                proposed = ""
                violations = ["no demo template matches this question and the LLM is off (stub mode)"]
            else:
                parsed, llm_meta = deps.llm_call("ask_sql", "ask_sql.md", dict(
                    question=question, schema=pool_schema_text(), dialect=dialect), SqlDraft, effort="medium")
                if parsed is None:
                    proposed = ""
                    violations = [f"the LLM did not return SQL ({llm_meta.get('stop_reason')})"]
                else:
                    proposed, rationale = parsed.sql.strip(), parsed.rationale
                    if not proposed:
                        violations = [f"the LLM declined: {rationale}"]

    g = guard.check_sql(proposed, dialect) if proposed and not violations else guard.GuardResult(False, violations)
    association = template.association if template else bool(_ASSOC_Q.search(question))
    result = dict(ask_id=ask_id, question=question, sql=g.sql if g.ok else proposed,
                  guard=dict(ok=g.ok, violations=g.violations), columns=[], rows=[], suppressed_cells=0,
                  sufficiency=dict(verdict="NOT_SUPPORTED", n=0, notes=[ASSOCIATION_NOTE] + g.violations),
                  summary=[], mode=mode, rationale=rationale,
                  template=template.key if template else None)

    if g.ok:
        try:
            raw = _run(db, g.sql)
        except Exception as e:  # noqa: BLE001 - surfaced to the researcher, audited
            g = guard.GuardResult(False, [f"query failed: {type(e).__name__}: {str(e).splitlines()[0][:200]}"])
            result["guard"] = dict(ok=False, violations=g.violations)
            result["sufficiency"]["notes"] = [ASSOCIATION_NOTE] + g.violations
        else:
            columns = list(raw[0].keys()) if raw else list(g.column_kinds.keys())
            raw_rows = [[r.get(c) for c in columns] for r in raw]
            rows, suppressed = anonymise(columns, raw_rows, g.column_kinds)
            suff = sufficiency(columns, raw_rows, g.column_kinds, suppressed, association,
                               template.notes if template else ())
            sentences, sum_meta = summarise(columns, rows, template)
            summary = []
            for s in sentences:
                reasons = critic(s["text"], s["cells"], columns, rows)
                if s.get("llm_failed"):
                    reasons.append("LLM summary failed")
                summary.append(dict(text=s["text"], cells=s["cells"],
                                    status="needs_review" if reasons else "verified", reasons=reasons))
            result.update(columns=columns, rows=rows, suppressed_cells=suppressed, sufficiency=suff, summary=summary)
            if sum_meta.get("prompt_hash"):
                deps.lineage_add(f"{ask_id}:summary", "ask_summary", [(ask_id, "ask")], "ask:summary",
                                 agent="summarizer", model=sum_meta.get("model"), prompt_hash=sum_meta["prompt_hash"])

    _persist(db, result, llm_meta, g)
    return result


def _persist(db, result: dict, llm_meta: dict, g: guard.GuardResult) -> None:
    ok = result["guard"]["ok"]
    sql_text = result["sql"] or ""
    sql_hash = store.sha256(sql_text)[:16] if sql_text else None
    db.insert_rows("research.asks", [dict(
        ask_id=result["ask_id"], question=result["question"], sql_text=sql_text, guard_ok=ok,
        guard_violations=store.dumps(result["guard"]["violations"]), n_rows=len(result["rows"]),
        suppressed_cells=result["suppressed_cells"], verdict=result["sufficiency"]["verdict"],
        summary_json=store.dumps(dict(summary=result["summary"], sufficiency=result["sufficiency"],
                                      columns=result["columns"], template=result["template"])),
        mode=result["mode"], created_at=store.now())])
    sources = [(t, "pool_view") for t in g.tables] if ok else []
    if sql_hash:
        sources.append((f"SQL:{sql_hash}", "sql"))
    if sources:
        deps.lineage_add(result["ask_id"], "ask", sources, f"ask:{result['mode']}",
                         agent="text_to_sql" if result["mode"] == "llm" else None,
                         model=llm_meta.get("model"), prompt_hash=llm_meta.get("prompt_hash"))
    payload = dict(question=result["question"], mode=result["mode"], template=result["template"], sql_hash=sql_hash,
                   verdict=result["sufficiency"]["verdict"], n_rows=len(result["rows"]),
                   suppressed_cells=result["suppressed_cells"], violations=result["guard"]["violations"])
    result["audit_seq"] = deps.audit_append(ACTOR, "ask.answered" if ok else "ask.blocked", result["ask_id"], payload)


def get_rare(db=None) -> dict:
    db = db or deps.get_db()
    if not deps.table_exists(db, "pool.rare_cases"):
        # Until Dev A's pool views exist: aggregate clinician-approved NEW symptoms straight from
        # community.symptoms (same columns, same k-anonymity), so approvals reach researchers.
        from app.research import pool

        return pool.rare_cases(db)
    items = []
    for r in db.query("SELECT term, exposure_label, age_band, sex, n_reports, first_month FROM pool.rare_cases "
                      "ORDER BY first_month DESC, term"):
        n = int(r["n_reports"] or 0)
        items.append(dict(term=r["term"], exposure_label=r["exposure_label"], age_band=r["age_band"], sex=r["sex"],
                          n_reports="<5" if n < K else str(n), first_month=r["first_month"]))
    return dict(k=K, items=items)
