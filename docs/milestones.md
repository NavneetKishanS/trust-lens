# TrustLens — Milestone Tracker (20 h)

Tick boxes as you merge to `main`. H = hours from start. Owner in brackets. Exit tests run in Swagger (`/docs`) or curl.
Rule: **no UI code before the MVP freeze at H11.** If something slips, cut scope inside the milestone (stub, template, fewer papers), never lineage or audit.

## M0 Foundation · H0–H2

- [ ] Exasol Personal launching on AWS eu-central-1 (A)
- [x] Synthea CSVs in `data/synthea/csv/` (or Kaggle fallback) (A)
- [x] `db/schema.sql`, `db.py`, `load.py` → curated loaded in DuckDB (A)
- [x] FastAPI skeleton, all §7 routes return stub shapes (B)
- [x] `llm.py` with stub / anthropic / bedrock; `gov.llm_calls` (B)
- [x] `audit.py` + `lineage.py`; `/audit`, `/audit/verify`, `/lineage/{id}` (B)
- [ ] Europe PMC fetch script started, caching JSON (C)
- [ ] Shared `ANON_SALT` agreed, `.env` on every laptop (all)

**Exit:** `/health` → db + llm + patient count; `data.loaded` is in the audit log and `/audit/verify` is valid.

## M1 Evidence-backed summaries · H2–H6

- [x] `ref.lab_ranges` + `db/facts.sql` (A, H4)
- [x] Generator + critic + verifier, patient + physician audiences (B)
- [x] `inject_error` (PL1) (B)
- [x] Lineage sentence → fact → row (B)

**Exit:** `GET /patients/{id}/summary?audience=patient` for 3 patients: every sentence cites facts, `/lineage/SEN-…` reaches OBS rows, no banned phrases; `inject_error=true` → flagged.

## M2 Symptom loop + review · H5–H9

- [x] `ref.known_effects`, `ref.symptom_vocab` (A, H5)
- [x] `db/pool_views.sql` + `db/pool_schema.md` (A, H6)
- [x] Symptom intake: extract → map → classify (B)
- [x] Review queue + decisions (B)
- [x] `data/seed_signal.py`: PL2 signal, PL3 reports, PL4 unsafe questions (A, H7)

**Exit:** "tired, headache and blurred vision" after CVX 207 → 2 EXPECTED + 1 NEW pending → approve → `/pool/rare` lists blurred vision as `"<5"`.

## M3 Researcher core · H2–H11

- [ ] ≥ 50 papers in `research.papers`, offline cache (C, H4)
- [ ] Ask the data: templates + guard + k-anon + sufficiency (C, H6)
- [ ] Ask the data: LLM text-to-SQL + cited summary (C, H8)
- [x] `ref.concepts` with synonyms (A, H7)
- [ ] A1 establish + A2 critic + citation edges (C, H9)
- [x] `exposure_outcome_rate` pool SQL (A, H9)
- [ ] A3 sanity: literature + pool (C, H11)
- [ ] Exasol live with everything; DuckDB still works (A, H10)

**Exit:** 5 demo questions answered with SQL + verdict; 5 unsafe ones blocked; `/research/graph?concept=CVX:207` returns cited edges with sanity labels; PL5 fabricated quote rejected.

## 🔒 MVP freeze · H11

- [ ] Whole demo path (shared §13) runs through Swagger on Exasol, and on DuckDB + stub as backup
- [ ] Tag `mvp` on `main`

## M4 Minimal UI · H11–H16 (C leads, A + B help)

- [ ] Patient page + lineage drawer + symptom box
- [ ] Physician page + `inject_error` toggle
- [ ] Review queue
- [ ] Researcher: Ask, rare cases, edge list (graph view if time)
- [ ] Audit page + Verify chain

## M5 Proof · H14–H17

- [ ] `/evals/latest`: PL1 catch rate, sentence support rate, PL3 classification accuracy, PL4 block rate, PL5 rejection (B)
- [ ] Tamper demo: edit one audit row → verify shows broken at #N (A)
- [ ] Every screen: AI text carries sources or "Unverified" (C)

## M6 Demo · H17–H20

- [ ] Rehearse the 3-minute script 3× with a timer (all)
- [ ] Backup screen recording at H18 (C)
- [ ] 5 slides: problem → trust gap → how it works → live demo → roadmap (C)

## Stretch (only after M5)

ElevenLabs voice for the patient summary · force-directed graph view · Exasol in-SQL AI functions for the verifier · second research topic · edge review by clinicians (`kind: kg_edge` in the queue)
