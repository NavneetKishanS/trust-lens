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
cp .env.example .env              # fill in credentials; never commit .env
# Generate Synthea CSVs (Java 17+) — see docs/context/01-dev-a-data.md §4
```
Backend run instructions will be added when the M0 skeleton lands.

## Data

All patient data is **synthetic** (Synthea). The research signal used in the demo is planted on purpose and labelled as such.
Paper abstracts are fetched from Europe PMC at build time and are not committed.
