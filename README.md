# TrustLens

**Every AI sentence is backed by data you can click through to, checked by other agents, and signed off by a human where it matters.**

Built for the Exasol × Medical Valley EMN Healthcare Hackathon Bayern (Erlangen, November 2026), challenge:
*"Would you trust an AI with your health?"*

| User | What they get |
|---|---|
| **Patient** | A plain-language overview of their records and lab results ("your blood sugar was high in March, now it's in the usual range"). No diagnoses, no advice. They can report new symptoms: listed side effects are recorded for statistics, unexpected ones go to a clinician |
| **Physician** | The same overview with clinical codes and clickable lineage, plus a review queue. The AI summarises; it never tells the doctor what to do |
| **Researcher** | A knowledge graph of research papers (relations established, criticised and sanity-checked by three agents, each with a verbatim quote and link), an anonymised patient pool with validated rare cases, and "Ask the data" with the SQL shown and small counts suppressed |

Every action is written to a **hash-chained audit log**; every output has **lineage** back to source rows or papers.

## Architecture

Diagrams: [`docs/architecture.md`](docs/architecture.md)

```
FastAPI  ──►  Exasol on AWS eu-central-1 (DuckDB fallback): curated Synthea EHR · ref · community · pool views · research · gov
   │     ──►  Claude Opus 5.5 (Bedrock EU / Anthropic API / stub)
   │     ──►  Europe PMC REST (papers)
   └── Next.js UI (after the MVP freeze)
```

## Team docs (start here)

| File | For |
|---|---|
| [`docs/context/00-shared.md`](docs/context/00-shared.md) | Everyone: scope, data and API contracts, decision rules, milestones, demo script |
| [`docs/milestones.md`](docs/milestones.md) | The 20-hour milestone tracker with owners and exit tests |
| [`docs/context/01-dev-a-data.md`](docs/context/01-dev-a-data.md) | Dev A: Exasol, Synthea load, facts SQL, anonymised pool, planted signal |
| [`docs/context/02-dev-b-clinical.md`](docs/context/02-dev-b-clinical.md) | Dev B: API core, LLM client, audit + lineage, patient/physician summaries, symptom loop, review |
| [`docs/context/03-dev-c-research.md`](docs/context/03-dev-c-research.md) | Dev C: papers, knowledge graph agents, Ask the data, then UI |
| [`CLAUDE.md`](CLAUDE.md) | AI coding agents: read this first |

## Quick start

```bash
cp .env.example .env              # fill in credentials; never commit .env (LLM_PROVIDER=stub works without any)
python3.12 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
.venv/bin/python -m pytest backend/tests -q
.venv/bin/uvicorn app.main:app --app-dir backend --reload --port 8000    # Swagger: http://localhost:8000/docs
# Generate Synthea CSVs (Java 17+) into data/synthea/csv/ — see docs/context/01-dev-a-data.md §4
cd backend && ../.venv/bin/python -m app.load --reset      # Synthea + ref tables -> DuckDB (or Exasol if EXASOL_DSN is set), ~15 s
../.venv/bin/python ../data/seed_signal.py                  # planted PL2/PL3/PL4 + demo patient (origin='seed_signal'), ~20 s
../.venv/bin/python -m app.factsql --check 5                # facts for 5 random patients; every source row must exist
../.venv/bin/python scripts/check_seed.py --demo             # PL2 by age band from the pool; M2 exit path for the demo patient
../.venv/bin/python scripts/smoke_summaries.py 10           # stub summaries for 10 real patients, both audiences
```
Without `EXASOL_DSN` the API uses a local DuckDB file (`data/trustlens.duckdb`). Without Synthea CSVs, `cd backend && ../.venv/bin/python -m app.devdata` adds 3 labelled dev-fixture patients instead. Stop the API before running the loader: DuckDB allows only one process to open the file. To reset before a demo rehearsal, run `app.load --reset` and `seed_signal.py` again. Responses with the header
`X-TrustLens-Stub: true` still return contract-shaped example data; `/health`, `/audit`, `/audit/verify` and `/lineage/{id}` are live.

### Research engine (Dev C)

```bash
cd backend
../.venv/bin/python -m app.research.papers              # fetch + cache Europe PMC papers (data/papers/, git-ignored)
../.venv/bin/python -m app.research.papers --offline    # reload from the cache only
../.venv/bin/python -m app.research.devpool             # DEV ONLY: stand-in pool.* tables until db/pool_views.sql exists
```
Then in Swagger: `POST /research/graph/build`, and try the questions from `GET /research/ask/templates`.
Before Dev A's `python -m app.load --reset`, run `python -m app.research.devpool --drop`.

## Data

All patient data is **synthetic** (Synthea). The research signal used in the demo is planted on purpose and labelled as such.
Paper abstracts are fetched from Europe PMC at build time and are not committed.
