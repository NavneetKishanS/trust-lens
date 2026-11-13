# TrustLens Research Studio: UI

Researcher-first frontend (Next.js App Router, TypeScript, plain CSS) on the existing FastAPI contract (`docs/context/00-shared.md` §7). No backend changes.

## Run

```bash
./start.sh            # API on :8000 + UI on :3000, Ctrl+C stops both
./start.sh --demo     # force the local demo database
./start.sh --reset    # rebuild the local demo database
```

- **Real data loaded** (`app.load --reset` + `data/seed_signal.py`, see README): `start.sh` uses it as is. It only adds papers and builds the knowledge graph if they are missing; it never touches `curated.*` or `pool.*`.
- **No real data**: `start.sh` creates `data/trustlens_demo.duckdb` (git-ignored, synthetic): 3 dev-fixture patients, the dev stand-in pool (1,000 synthetic patients with a planted PL2-style signal), papers from the `data/papers/` cache, and a graph build.
- First run installs Python and npm packages if needed. If there is no `data/papers/` cache, papers are fetched from Europe PMC (~2 min).
- Setup logic lives in `scripts/dev_setup.py`.

## Screens

| Route | Screen | API |
|---|---|---|
| `/` | Research Overview: live metrics, the three linked entry points, suggested question, 10-step guided path | `/health`, `/research/graph`, `/pool/rare`, `/research/ask/templates`, `/audit` |
| `/graph` | Knowledge Graph: interactive graph (zoom, pan, fit, drag), filters, list view, evidence inspector | `/research/graph`, `/research/edges/{id}`, `/research/graph/build` |
| `/ask` | Ask the Data: query workbench, verdict, causation banner, cited summary, chart, k-anon table, SQL inspector, guard panel, lineage | `/research/ask`, `/research/ask/templates`, `/lineage/{id}` |
| `/cohorts` | Cohort Explorer: report → classification → approval → pool pathway, filterable rare-case table | `/pool/rare`, `/research/ask` |
| `/review` | Clinical Review: approve / reject flagged sentences and NEW symptoms | `/review/queue`, `/review/{id}` |
| `/audit` | Trust & Audit: Verify integrity, event history, lineage tracer, honest DB / AI status | `/audit`, `/audit/verify`, `/lineage/{id}`, `/health` |
| `/patients`, `/patient/[id]`, `/physician/[id]` | Patient and physician summaries (unchanged features, new layout) | `/patients`, `/patients/{id}/summary`, `/patients/{id}/reports` |

`/research` redirects to `/`. Deep links: `/graph?concept=CVX:207&depth=2&edge=EDG-…`, `/ask?q=hypertension_after_moderna`.

## Trust rules the UI follows

- Shows only values the API returns; no invented metrics, nodes, quotes or confidence scores.
- Status is always colour + icon + text. AI text without sources is labelled "Unverified".
- `"<5"` and blank cells are suppressed values, drawn as hatched bars, never used as numbers.
- "Association only, not causation" is shown prominently on every answered query.
- The PL2 hypertension signal is labelled "Planted synthetic signal" wherever it appears.
- The top bar shows the database and LLM exactly as `/health` reports them (never "Exasol" when it is DuckDB).

## Code layout

- `frontend/components/shell/`: sidebar, top bar, navigation config
- `frontend/components/kg/`: graph canvas (SVG) and evidence / node inspectors
- `frontend/lib/graphLayout.ts`: small deterministic force layout (no graph library)
- `frontend/lib/kg.ts`: relation wording, colours, suggested concepts
- `frontend/components/ask/ResultChart.tsx`: bar chart that respects suppression
- `frontend/app/globals.css`: the design system (tokens, shell, tables, badges, graph, workbench)

## Known limits

- The paper panel has no journal name: `/research/edges/{id}` doesn't return it.
- In the demo data no "contested" relationship touches Moderna directly; contested edges are reachable from the whole-graph view. Real data or a live LLM build may differ.
- The stub-mode establisher finds relations by keyword co-occurrence, so some edges are weak. The A2 critic still guarantees every quote is verbatim.
- The graph is tuned for up to ~150 nodes; very large builds will be slower and busier.
- Desktop first (1440px). Below 960px the sidebar stacks on top; usable but not polished for phones.
- The Ask chart picks one rate / average / count column automatically; queries with unusual columns may show the table only.
- `start.sh` needs ports 8000 and 3000 free, and DuckDB allows one process per file, so stop other servers first.
