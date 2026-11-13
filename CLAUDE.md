# TrustLens — agent instructions

Hackathon project (Exasol × Medical Valley, Erlangen, Nov 2026): evidence-backed AI summaries for patients and physicians,
a patient symptom loop with clinician review, and a researcher engine (knowledge graph agents + Ask the data over an anonymised pool),
all with audited lineage and a hash-chained audit log.

Before writing any code:
1. Read `docs/context/00-shared.md` (v2). It holds the contracts (tables, API, decision rules, audit hash) and is the source of truth.
2. Check `docs/milestones.md` for the current milestone. **Backend MVP first; no UI code before the H11 freeze.**
3. Read the context file for your slice:
   - Data / Exasol / Synthea / facts SQL / pool views → `docs/context/01-dev-a-data.md`
   - API core / LLM / audit / lineage / summaries / symptoms / review → `docs/context/02-dev-b-clinical.md`
   - Papers / knowledge graph agents / Ask the data / UI → `docs/context/03-dev-c-research.md`

Rules:
- Don't change table names, columns, endpoint paths or JSON shapes unless you update `00-shared.md` in the same change.
- Stay inside your slice's folders unless told otherwise.
- SQL and rules decide; the LLM only extracts and phrases, and its output is checked by a deterministic critic.
- Every output gets lineage and an audit event. Never skip them to save time.
- Stub mode (`LLM_PROVIDER=stub`) must always work.
- Synthetic data only; planted rows are labelled `origin='seed_signal'`. Never commit secrets, Synthea output or paper abstracts.
