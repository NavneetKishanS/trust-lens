# TrustLens — agent instructions

Hackathon project (Exasol × Medical Valley, Erlangen, Nov 2026): a healthcare AI that checks whether data can
answer a question before answering, with verdicts, lineage, human review and a hash-chained audit log.

Before writing any code:
1. Read `docs/context/00-shared.md`. It holds the contracts (tables, API, verdict rules, audit hash) and is the source of truth.
2. Read the context file for the slice you're working on:
   - Data / Exasol / SQL checks → `docs/context/01-dev-a-data.md`
   - Backend / agents / evals → `docs/context/02-dev-b-agents.md`
   - Frontend / demo → `docs/context/03-dev-c-frontend.md`

Rules:
- Don't change table names, columns, endpoint paths or JSON shapes unless you update `00-shared.md` in the same change.
- Stay inside your slice's folders unless told otherwise.
- Rules and SQL decide verdicts; the LLM only explains, extracts or drafts, and its output is validated against the DB.
- Synthetic data only. Never commit secrets (`.env` is git-ignored).
