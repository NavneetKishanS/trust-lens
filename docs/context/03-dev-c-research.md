# Dev C — Researcher Engine: Knowledge Graph Agents + Ask the Data (then UI lead)

> Read `00-shared.md` first (v2). This file covers only your slice. Milestone tags: **[M3]**, **[M4]**…

## 1. Mission

The researcher is our power user. Give them (a) a knowledge graph of research where every relation is established by one agent,
attacked by a second and sanity-checked by a third, with the exact quote and a link to the paper, and (b) "Ask the data": natural-language
questions over the **anonymised** pool, answered with the SQL shown, small counts suppressed, and a cited summary.
After the MVP freeze (H11) you lead the minimal UI.

## 2. Deliverables

| Milestone | Deliverable | By | Notes |
|---|---|---|---|
| M3 | Paper ingestion from Europe PMC into `research.papers` + local JSON cache | H4 | Start H0–H2 while Dev A loads Synthea |
| M3 | Ask the data: template mode (5 demo questions) + guard + k-anon + sufficiency | H6 | Uses Dev A's pool views (DuckDB) |
| M3 | Ask the data: LLM text-to-SQL + cited summary | H8 | |
| M3 | Graph: A1 establish → A2 critic → citation edges | H9 | |
| M3 | A3 sanity: literature consistency + pool check | H11 | Needs Dev A's `exposure_outcome_rate` (H9) |
| M3 | `/pool/rare`, `/research/graph`, `/research/edges/{id}` live | H11 | |
| M4 | Minimal Next.js UI on the live API | H11–H16 | See §7 |

## 3. Paper ingestion **[M3]** (`research/papers.py`)

Europe PMC REST API, free, no key:
```
GET https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=<q>&format=json&resultType=core&pageSize=100
GET https://www.ebi.ac.uk/europepmc/webservices/rest/MED/<pmid>/references?format=json&pageSize=1000
```
- Topic `covid_vaccine_safety`, queries such as `"mRNA-1273" AND (adverse OR safety)`, `"COVID-19 vaccine" AND hypertension`,
  `"COVID-19 vaccine" AND myocarditis`. Mix older and recent years (sort by date and by citations) so the graph shows old vs new research.
  Add a second topic from conditions common in our Synthea data (e.g. metformin and type 2 diabetes) if time allows.
- Keep only records with an abstract and a PMID. Store pmid, doi, title, journal, pub_year, abstract_text, `source_url = https://europepmc.org/article/MED/<pmid>`, query.
- Cache raw JSON in `data/papers/` (git-ignored; don't commit abstracts). The build must run offline from the cache.
- References: for each paper, keep references whose PMID is also in our corpus → `CIT-` edges (`CITES`). Deterministic, no LLM.

## 4. Knowledge graph agents **[M3]**

Graph lives in Exasol tables (`research.edges`, `research.citations`, nodes = `ref.concepts` + papers). No graph database.
`POST /research/graph/build` runs the steps below for up to `max_papers` papers; audit `kg.built`, and `edge.accepted` / `edge.rejected` per edge.

**A1 Establisher** (LLM, effort `low`, `prompts/kg_establish.md`). Per abstract, return at most 5:
`{relations:[{subject, relation, object, quote}]}` with `relation` ∈
`ASSOCIATED_WITH, INCREASES_RISK_OF, DECREASES_RISK_OF, ADVERSE_EVENT_OF, TREATS, NO_ASSOCIATION_WITH`.
`quote` must be one sentence copied verbatim from the abstract. Stub: regex over sentences containing two concept synonyms → `ASSOCIATED_WITH`.

**Concept resolution:** map `subject`/`object` to `ref.concepts` by exact or synonym match (lowercase). Unmatched → `FREE:<slug>` node (shown grey, lower trust).

**A2 Critic** (deterministic, `research/critic.py`). FAIL if any of:
- the quote is not a verbatim substring of the abstract (after normalising whitespace and quotes)
- subject or object (or one of their synonyms) does not appear in the quote
- `NO_ASSOCIATION_WITH` without a negation cue in the quote ("no ", "not ", "did not", "was not associated"), or a positive relation **with** one
- relation not in the vocabulary, or subject == object
- duplicate of an existing edge from the same paper

**A3 Sanity checker** (`research/sanity.py`, deterministic SQL; the LLM may only phrase the label):
- *Literature:* count other ACCEPTED edges for the same concept pair; same direction → `support_count`, opposite (positive vs `NO_ASSOCIATION_WITH` / increases vs decreases) → `contradict_count`.
  `lit_status` = `CONTESTED` if contradict > 0, `CONSISTENT` if support > 0, else `SINGLE_SOURCE`. Also store the newest and oldest supporting year.
- *Pool:* if both concepts exist in our pool (e.g. `CVX:207` and the hypertension code), run Dev A's `exposure_outcome_rate` → `OBSERVED` (exposed rate > baseline and n ≥ 20), `NOT_OBSERVED`, or `UNTESTABLE` (concept not in the data or n too small). Store the SQL and numbers in `pool_evidence_json`.
- Edges with `CONTESTED` are interesting for researchers, not errors. Sanity never deletes; it labels.

Lineage: edge → paper (agent `establisher`, model, prompt_hash), edge → critic result, edge → pool SQL.

## 5. Ask the data **[M3]** (`research/ask.py`, `research/guard.py`)

Pipeline for `POST /research/ask`:
1. **Template match first**: 5 demo questions with hand-written SQL (keyword match), so the demo works in stub mode. For example:
   "hypertension after Moderna by age band", "most common reported symptoms after vaccination", "rare validated symptoms",
   "average HbA1c by age band", "patients on metformin by sex".
2. **Text-to-SQL** (LLM, effort `medium`, `prompts/ask_sql.md` containing Dev A's `db/pool_schema.md`): `{sql, rationale}`.
3. **Guard** (`guard.py`, sqlglot): exactly one statement, a `SELECT` only; every table is in `pool.*`; no `*` on `pool.patients`; no
   `pseudo_id` in the output columns unless aggregated; adds `LIMIT 1000`; statement timeout. Any violation → `guard.ok=false`, audit `ask.blocked`, no execution.
4. **Run** read-only via `db.query`.
5. **k-anonymity**: any count-like column (name starts with `n_` or `count`) with a value < 5 → `"<5"`; also blank any rate computed from it. Return all cells as strings; report `suppressed_cells`.
6. **Sufficiency** per shared §8 → verdict + notes (always include "Association only, not causation").
7. **Summary** (LLM, effort `low`): input = columns + rows only. Output `[{text, cells:[[row_index, column]]}]`.
   Critic: every number in the text appears in a cited cell; no causal words; no `"<5"` cell turned into a number. Failing sentences → `needs_review`.
   Stub: one templated sentence per row (max 3).
8. Persist `research.asks`, lineage ask → pool views + SQL hash, audit `ask.answered`.

## 6. `/pool/rare`

Read `pool.rare_cases`, map `n_reports < 5` to `"<5"`, return the shared §7 shape.

## 7. Minimal UI **[M4]** (after H11 only)

Next.js (App Router, TypeScript), plain CSS, dark teal `#062A38` + green `#5CC33F`. Types copied from shared §7. Screens, in priority order:
1. `/patient/[id]`: summary sections; click a sentence → lineage drawer; symptom report box showing the classification chips.
2. `/physician/[id]`: same with codes and flags; `inject_error` toggle.
3. `/review`: queue with approve/reject.
4. `/research`: Ask box (SQL in a code block, verdict badge, table, cited summary), rare cases table, graph view
   (start with a list of edges with quote + paper link; add a force graph like `react-force-graph` only if time allows).
5. `/audit`: list + Verify chain button.
Every AI sentence shows its sources or "Unverified". Status always as colour + icon + text.

## 8. Definition of done

- [ ] ≥ 50 papers ingested and cached; build runs offline
- [ ] Graph build produces ACCEPTED edges, each with a verbatim quote and a working Europe PMC link
- [ ] PL5 (fabricated quote) is REJECTED by A2
- [ ] At least one edge around CVX 207 shows A3 pool evidence from the planted signal (and is labelled synthetic in the UI)
- [ ] Ask the data answers the 5 demo questions in stub mode and with the LLM; blocks all 5 PL4 unsafe questions
- [ ] No count under 5 ever leaves the API as a number

## 9. Pitfalls

- Abstract text is copyrighted: cache locally, show one quote sentence plus the link, don't republish whole abstracts.
- Never let the LLM write to the DB or query outside `pool.*`. The guard runs before execution, every time.
- Text-to-SQL is flaky; the template path is the demo path, the LLM path is the "and it also works on new questions" moment.
