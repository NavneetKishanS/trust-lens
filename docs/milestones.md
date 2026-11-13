# TrustLens — Milestone Tracker (20 h)

Tick boxes as you merge to `main`. H = hours from start. Owner in brackets. Exit tests run in Swagger (`/docs`) or curl.
Rule: **no UI code before the MVP freeze at H11.** If something slips, cut scope inside the milestone (stub, template, fewer papers), never lineage or audit.

## M0 Foundation · H0–H2

- [ ] Exasol Personal launching on AWS eu-central-1 (A)
- [ ] Synthea CSVs in `data/synthea/csv/` (or Kaggle fallback) (A)
- [ ] `db/schema.sql`, `db.py`, `load.py` → curated loaded in DuckDB (A)
- [x] FastAPI skeleton, all §7 routes return stub shapes (B)
- [x] `llm.py` with stub / anthropic / bedrock; `gov.llm_calls` (B)
- [x] `audit.py` + `lineage.py`; `/audit`, `/audit/verify`, `/lineage/{id}` (B)
- [x] Europe PMC fetch script started, caching JSON (C)
- [ ] Shared `ANON_SALT` agreed, `.env` on every laptop (all)

**Exit:** `/health` → db + llm + patient count; `data.loaded` is in the audit log and `/audit/verify` is valid.

## M1 Evidence-backed summaries · H2–H6

- [ ] `ref.lab_ranges` + `db/facts.sql` (A, H4)
- [x] Generator + critic + verifier, patient + physician audiences (B)
- [x] `inject_error` (PL1) (B)
- [x] Lineage sentence → fact → row (B)

**Exit:** `GET /patients/{id}/summary?audience=patient` for 3 patients: every sentence cites facts, `/lineage/SEN-…` reaches OBS rows, no banned phrases; `inject_error=true` → flagged.

## M2 Symptom loop + review · H5–H9

- [ ] `ref.known_effects`, `ref.symptom_vocab` (A, H5)
- [ ] `db/pool_views.sql` + `db/pool_schema.md` (A, H6)
- [ ] Symptom intake: extract → map → classify (B)
- [ ] Review queue + decisions (B)
- [ ] `data/seed_signal.py`: PL2 signal, PL3 reports, PL4 unsafe questions (A, H7)

**Exit:** "tired, headache and blurred vision" after CVX 207 → 2 EXPECTED + 1 NEW pending → approve → `/pool/rare` lists blurred vision as `"<5"`.

## M3 Researcher core · H2–H11

- [x] ≥ 50 papers in `research.papers`, offline cache (C, H4) — 332 papers, 729 citation links
- [x] Ask the data: templates + guard + k-anon + sufficiency (C, H6)
- [x] Ask the data: LLM text-to-SQL + cited summary (C, H8) — tested with a fake LLM; not yet run against live Claude
- [ ] `ref.concepts` with synonyms (A, H7)
- [x] A1 establish + A2 critic + citation edges (C, H9)
- [ ] `exposure_outcome_rate` pool SQL (A, H9)
- [x] A3 sanity: literature + pool (C, H11) — uses a fallback `exposure_outcome_rate` until Dev A's lands
- [ ] Exasol live with everything; DuckDB still works (A, H10)

**Exit:** 5 demo questions answered with SQL + verdict; 5 unsafe ones blocked; `/research/graph?concept=CVX:207` returns cited edges with sanity labels; PL5 fabricated quote rejected.

## 🔒 MVP freeze · H11

- [ ] Whole demo path (shared §13) runs through Swagger on Exasol, and on DuckDB + stub as backup
- [ ] Tag `mvp` on `main`

## M4 Minimal UI · H11–H16 (C leads, A + B help)

- [ ] Patient page + lineage drawer + symptom box — built to the §7 contract; waiting for Dev B's endpoints
- [ ] Physician page + `inject_error` toggle — built; waiting for Dev B's endpoints
- [ ] Review queue — built; waiting for Dev B's endpoints
- [x] Researcher: Ask, rare cases, edge list (graph view if time) — edge list, no force graph
- [x] Audit page + Verify chain

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
