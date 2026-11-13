# TrustLens — Shared Context (everyone reads this first)

> Single source of truth for the team and for every AI coding agent working on the repo.
> If you change a contract in here (§6–§9), tell the other two devs right away.
> **Version 2** (after mentor feedback, 13 Nov). We have **20 hours**. Backend MVP first, UI after the MVP freeze.

## 1. What we are building

**Challenge:** Exasol × Medical Valley EMN, Healthcare Hackathon Bayern, Erlangen. "Would you trust an AI with your health?"

**One-liner:** *Every AI sentence in TrustLens is backed by data you can click through to, checked by other agents, and signed off by a human where it matters.*

**Star fundamentals (never trade these away):**
1. **Evidence-backed:** the LLM only puts into words facts that SQL computed or text that a paper contains verbatim. Every sentence carries the IDs of its sources.
2. **Audited lineage:** every output traces to source rows or papers, the agent, model and prompt hash. Every action is in a hash-chained audit log.
3. **Multi-agent governance:** one agent produces, a second criticises (mostly deterministic), a third sanity-checks. Disagreements go to a human.

**Three users, one engine:**

| User | Gets | Never |
|---|---|---|
| **Patient** | AI overview of their history and lab results in simple words ("your glucose was high in March, now it's in the usual range; your care plan is with Dr X"). Can report new symptoms or side effects | No diagnoses ("you seem to have…"), no treatment advice, no guesses |
| **Physician** | The same overview for one patient with clinical depth: codes (SNOMED CT, LOINC, RxNorm, CVX), trends, and clickable lineage. Reviews flagged items | The AI never tells the doctor what to do. It summarises to save time |
| **Researcher** (power user) | (a) **Knowledge graph** of research papers with agent-established, cited relations; (b) **anonymised patient pool** to explore (similar symptoms, cohorts, clinically validated rare cases); (c) **Ask the data**: natural-language questions → guarded SQL → cited AI summary | No raw identities, no counts under k=5, no causal claims from observational data |

**Patient symptom loop:** a patient writes "since my booster I'm tired, have a headache and blurred vision".
- *tired*, *headache* → listed side effects of the vaccine they got (or already in the doctor's record) → **recorded for statistics**, no review.
- *blurred vision* → not expected and not in the record → **flagged for clinician review** → if approved, it enters the research pool as a validated rare case.

> Demo note: "knee pain" maps to *joint pain*, which **is** a listed Moderna side effect, so it would be classed EXPECTED. Use a symptom off the list (e.g. blurred vision) for the NEW case.

**Not in MVP:** ElevenLabs voice, fancy graph visualisation, Exasol in-SQL AI functions, real EHR integration, blockchain.

## 2. The trust story (what the jury must see)

1. Click any AI sentence → see the exact fact, the source rows, the agent, model and prompt hash.
2. The critic catches a planted wrong number in a summary (`inject_error=true`), and it lands in the review queue.
3. A patient's new symptom is flagged, a clinician approves it, and it shows up in the researcher's rare-case pool.
4. A knowledge-graph edge shows the verbatim quote, the paper link, and the sanity agent's verdict (consistent / contested / seen in our pool).
5. "Ask the data" shows the generated SQL, refuses an unsafe query, suppresses small counts, and states "association only".
6. **Verify chain** recomputes the audit log live; editing one row in the DB breaks it.

## 3. Architecture

```
            ┌──────────────────────────── FastAPI (one service) ────────────────────────────┐
Patient  ─┐ │ Clinical engine (Dev B)          Research engine (Dev C)        Governance      │
Physician ┼─► facts → generator → critic →     papers → A1 establish →        audit chain     │──► Exasol (AWS eu-central-1)
Researcher┘ │ verifier → review queue          A2 critic → A3 sanity          lineage         │    raw · curated · ref · clinical
  (Swagger  │ symptom intake → match →         Ask the data: NL → SQL →       llm call log    │    community · pool(views) · research
  until H11)│ review → pool                    guard → k-anon → summary       review queue    │    gov · evals      (DuckDB fallback)
            └───────────────────────────────────────────────────────────────────────────────┘──► Claude (Bedrock / API / stub)
                                                                                                ──► Europe PMC REST (papers)
```
Detailed diagrams: `docs/architecture.md`.

| Layer | Owner | Tech |
|---|---|---|
| Exasol, Synthea load, curated + ref tables, **facts SQL**, anonymised pool views, seeded signal | **Dev A** | Exasol Personal on AWS, pyexasol, DuckDB fallback |
| FastAPI core, LLM client, audit + lineage libs, patient/physician summaries, symptom intake, review queue | **Dev B** | FastAPI, Anthropic SDK, Pydantic |
| Paper ingestion, knowledge graph agents (A1/A2/A3), Ask the data | **Dev C** | Python, Europe PMC REST, sqlglot |
| UI (after H11) | **Dev C leads**, A and B help | Next.js |

## 4. Repo layout

```
trustlens/
  CLAUDE.md                       # agent entry point → points here
  docs/context/                   # these files; docs/milestones.md is the tracker
  data/synthea/csv/               # Synthea CSV output (git-ignored)
  data/papers/                    # Europe PMC JSON cache (git-ignored)
  data/seed_signal.py             # planted reports + signal (Dev A)
  db/schema.sql                   # all tables (Dev A)
  db/facts.sql                    # per-patient facts, '-- name: <kind>' blocks, '?' = patient_id; data columns packed by app/factsql.py (Dev A)
  db/pool_views.sql               # anonymised views (Dev A)
  db/pool_schema.md               # view/column list pasted into the text-to-SQL prompt (Dev A)
  backend/app/
    main.py  llm.py  audit.py  lineage.py  models.py        # Dev B
    db.py  load.py                                          # Dev A
    clinical/  (summary.py, critic.py, verifier.py, symptoms.py, review.py)   # Dev B
    research/  (papers.py, establish.py, critic.py, sanity.py, ask.py, guard.py)  # Dev C
    prompts/*.md                                            # prompt files, hashed for lineage
    routes/                                                 # one file per §7 group
  frontend/                       # after H11
```
Branches: `data/*` (A), `clin/*` (B), `res/*` (C). Merge to `main` small and often; keep `main` runnable.

## 5. Data source and glossary

**Data:** synthetic EHR from **Synthea** (https://github.com/synthetichealth/synthea), CSV export, ~1,000 living patients, seed 42.
Fallback: the Synthea CSV dataset on Kaggle (needs a Kaggle login to download). No real patient data, ever.

| Term | Meaning |
|---|---|
| **Row ID** | Stable ID we assign on load. Prefix = table: `PAT` patient, `ENC` encounter, `CON` condition, `OBS` observation, `MED` medication, `IMM` immunization, `CPL` care plan, `ALG` allergy, `PRC` procedure. Format `OBS-0004411` |
| **Fact** | One deterministic statement computed by SQL for one patient (e.g. a lab trend), with `source_row_ids`. ID `FCT-…` |
| **Sentence** | One LLM-written sentence that cites `fact_ids`. ID `SEN-…` |
| **Report / Symptom** | A patient's free-text report (`RPT-…`) and each symptom extracted from it (`SYM-…`) |
| **Classification** | `EXPECTED` (known side effect in window) · `IN_RECORD` (doctor already documented it) · `NEW` (needs review) · `UNMAPPED` (couldn't map, needs review) |
| **Pseudo ID** | `ANON-` + first 12 hex of `sha256(ANON_SALT + patient_uuid)`. Only ID visible in the pool |
| **Paper** | `PMID:<pmid>` from Europe PMC |
| **Concept** | A graph node for a clinical entity, keyed by code where possible: `SNOMED:59621000`, `CVX:207`, `RXNORM:860975`, `LOINC:4548-4`; unmatched entities get `FREE:<slug>` |
| **Edge** | `EDG-…` agent-established relation with a verbatim quote, or `CIT-…` a citation link between papers |
| **Ask** | One "Ask the data" question → `ASK-…` |
| **Lineage edge** | derived artefact → source, with transform, agent, model and prompt hash |

## 6. Data contract

All lowercase. Synthea columns that are reserved words get renamed on load (`date`→`obs_date`/`imm_date`, `value`→`value_text` + `value_num`, `start`/`stop`→`start_ts`/`stop_ts` or `start_date`/`stop_date`, `code`→`concept_code`).

**curated** (from Synthea; `patient_id` = Synthea UUID)
- `curated.patients(row_id, patient_id, display_name, birth_date, death_date, sex, race, ethnicity, state)` — identifying columns (SSN, address, lat/lon, passport, drivers) are **not** loaded
- `curated.encounters(row_id, encounter_id, patient_id, start_ts, stop_ts, encounter_class, concept_code, description, reason_code, reason_description, provider_name, organization_name)`
- `curated.conditions(row_id, patient_id, encounter_id, start_date, stop_date, code_system, concept_code, description)`
- `curated.observations(row_id, patient_id, encounter_id, obs_date, category, concept_code, description, value_text, value_num, units, value_type)`
- `curated.medications(row_id, patient_id, encounter_id, start_ts, stop_ts, concept_code, description, reason_code, reason_description)`
- `curated.immunizations(row_id, patient_id, encounter_id, imm_date, concept_code, description)`
- `curated.careplans(row_id, careplan_id, patient_id, encounter_id, start_date, stop_date, concept_code, description, reason_code, reason_description)`
- `curated.allergies(row_id, patient_id, start_date, stop_date, concept_code, description, category)`
- every curated row also has `source_file, source_line, origin` where `origin` is `synthea` or `seed_signal` (planted rows are always labelled)
- `curated.age_bands(age_years, age_band)` — lookup used by the pool views ('40-49', '90+'); `curated.v_pool_person` and `curated.v_pool_symptoms` are the pool's helper views. None of these is readable by Ask the data
- `curated.pseudo_ids(patient_id, pseudo_id)` — the pseudonym map (§5), computed in Python at load so the salt never sits in the DB. Lives in `curated`, so Ask the data can't read it
- DDL: `db/schema.sql` (raw, curated, ref, community, pool, research, evals); `db/gov_schema.sql` + `db/clinical_schema.sql` (Dev B). Timestamps the API writes are ISO-8601 text
- **Exasol reserved words in our names:** `ref`, `text`, `section`, `state`, `low`, `high`, `transform`. `app/db.py` quotes them automatically on Exasol; write them lowercase and unquoted. Don't introduce new ones (`backend/tests/exasol_reserved_words.txt`, checked by `test_data.py`)

**ref** (small, hand-made, Dev A)
- `ref.lab_ranges(loinc, name, units, low, high, plain_name)` — demo ranges, not clinical advice
- `ref.known_effects(effect_id, product_system, product_code, product_name, effect_term, window_days, source_title, source_url)`
- `ref.symptom_vocab(term, synonyms, snomed_code)` — synonyms are `;`-separated
- `ref.concepts(concept_id, code_system, concept_code, label, synonyms)` — built from distinct codes in curated + hand-added synonyms (e.g. "Moderna; mRNA-1273; Spikevax" → `CVX:207`)

**clinical** (Dev B writes)
- `clinical.facts(fact_id, patient_id, kind, data_json, source_row_ids, computed_at)` — `kind` ∈ `LAB_TREND, CONDITION, MEDICATION, IMMUNIZATION, ENCOUNTER, CAREPLAN, ALLERGY, NEXT_STEP`
- `clinical.summaries(summary_id, patient_id, audience, inject_error, overall_status, model, prompt_hash, created_at)`
- `clinical.sentences(sentence_id, summary_id, sort_order, section, sentence_text, fact_ids, critic_status, critic_reasons, verifier_status, verifier_reason, review_status, reviewed_by, reviewed_at)` — `review_status` ∈ `auto_ok, needs_review, approved, rejected`
- DDL for `gov` and `clinical`: `db/gov_schema.sql`, `db/clinical_schema.sql` (the API creates them on startup)

**community** (Dev B writes)
- `community.reports(report_id, patient_id, report_text, onset_date, submitted_at, origin)` — `origin` ∈ `patient` (default), `seed_signal` (planted PL3 reports from `data/seed_signal.py`)
- `community.symptoms(symptom_id, report_id, patient_id, span, term, snomed_code, classification, reason, evidence_json, exposure_code, exposure_label, exposure_date, onset_date, review_status, reviewed_by, reviewed_at, review_note, created_at)` — `review_status` ∈ `not_required, pending, approved, rejected`; `exposure_*` = the vaccine/medicine the symptom was matched to (EXPECTED) or the latest one within 90 days before onset (NEW), so pool views can group by it
- DDL: `db/community_schema.sql` (created on startup)

**pool** (views only, Dev A; the **only** schema Ask the data may read)
- `pool.patients(pseudo_id, age_band, sex, race, ethnicity)` — age band = 10-year bands
- `pool.conditions(pseudo_id, concept_code, description, onset_month, age_band_at_onset)`
- `pool.observations(pseudo_id, concept_code, description, value_num, units, obs_month)`
- `pool.medications(pseudo_id, concept_code, description, start_month, stop_month)`
- `pool.immunizations(pseudo_id, concept_code, description, imm_month, age_band_at_dose)`
- `pool.symptom_reports(pseudo_id, term, classification, exposure_code, exposure_label, days_since_exposure, report_month)` — EXPECTED, IN_RECORD and **approved** NEW only
- `pool.rare_cases(term, exposure_label, age_band, sex, n_reports, first_month)` — approved NEW only; `n_reports` is shown as `"<5"` when under 5

**research** (Dev C writes)
- `research.papers(paper_id, pmid, doi, title, journal, pub_year, abstract_text, source_url, query, fetched_at)`
- `research.edges(edge_id, run_id, src_id, dst_id, relation, quote, paper_id, critic_status, critic_reasons, lit_status, support_count, contradict_count, pool_status, pool_evidence_json, status, created_at)`
- `research.citations(edge_id, citing_paper_id, cited_paper_id)`
- `research.asks(ask_id, question, sql_text, guard_ok, guard_violations, n_rows, suppressed_cells, verdict, summary_json, mode, created_at)`

**gov** (Dev B writes through `audit.py` / `lineage.py`)
- `gov.audit_events(seq, event_ts, actor, action_type, subject, payload_json, prev_hash, row_hash)`
- `gov.lineage_edges(derived_id, derived_type, source_id, source_type, transform, agent, model, prompt_hash, created_at)`
- `gov.llm_calls(call_id, purpose, model, prompt_hash, input_hash, stop_reason, latency_ms, ok, created_at)`

**evals** (M5)
- `evals.planted(item_id, kind, description, expected)` — planted signal, injected errors, unsafe queries
- `evals.runs(eval_id, metric_name, metric_value, detail_json, created_at)`

## 7. API contract (MVP)

Base `http://localhost:8000`, JSON. Errors: `{"error":{"code":"...","message":"..."}}`. Until H11 the UI is FastAPI's `/docs` (Swagger).
Every write endpoint returns `audit_seq`.

### System
- `GET /health` → `{"status":"ok","db":"exasol|duckdb","llm":"bedrock|anthropic|stub","counts":{"patients":1000,"papers":0}}`
  Also returned: `llm_region` (AWS region for bedrock, else null), `llm_eu_only` (bedrock: EU region and no `us.`/`global.`/`apac.`
  cross-region inference profile, else false; null when not bedrock), `db_location` (`local|remote`). The UI shows "EU" only when `llm_eu_only` is true.

### Clinical (Dev B)
- `GET /patients?limit=20&vaccinated=true` → `[{"patient_id":"<uuid>","display_name":"Synthetic Name","age":57,"sex":"F","last_encounter":"2026-05-02"}]`
- `GET /patients/{patient_id}/facts` → `{"patient_id":"...","facts":[Fact]}`
- `GET /patients/{patient_id}/summary?audience=patient|physician&inject_error=false` →
  ```json
  {"summary_id":"SUM-...","patient_id":"...","audience":"patient","overall_status":"verified|needs_review",
   "sections":[{"title":"Your lab results","sentences":[
     {"sentence_id":"SEN-...","text":"Your glucose was 142 mg/dL in March 2025, above the usual range. In October 2025 it was 91 mg/dL, in the usual range.",
      "fact_ids":["FCT-..."],"status":"verified|needs_review|hidden_pending_review",
      "critic":{"status":"PASS|FLAG","reasons":[]},"verifier":{"status":"SUPPORTED|UNSUPPORTED|UNSURE","reason":"..."}}]}],
   "facts":[{"fact_id":"FCT-...","kind":"LAB_TREND","data":{"loinc":"2339-0","name":"Glucose","units":"mg/dL",
      "latest":{"value":91,"date":"2025-10-02","flag":"NORMAL"},"previous":{"value":142,"date":"2025-03-11","flag":"HIGH"}},
      "source_row_ids":["OBS-0004411","OBS-0005120"]}],
   "model":"claude-opus-5-5|stub","prompt_hash":"ab12...","audit_seq":12}
  ```
  Patient sections: *Your lab results · Your visits and care plans · Medicines and vaccines · Next steps*. Patient view uses no CONDITION facts.
  Physician sections: *Labs (LOINC) · Active problems (SNOMED CT) · Medications (RxNorm) · Immunizations (CVX) · Encounters · Care plans · Allergies*.
  In the patient view a flagged sentence is replaced by "Part of this summary is waiting for your care team to check it." (`hidden_pending_review`).
- `POST /patients/{patient_id}/reports` body `{"text":"...","onset_date":"2026-11-01"|null}` →
  ```json
  {"report_id":"RPT-...","patient_id":"...","symptoms":[
    {"symptom_id":"SYM-...","span":"blurred vision","term":"blurred vision","snomed_code":null,"classification":"NEW",
     "reason":"Not a listed effect of Moderna (CVX 207) and not in the patient's record",
     "evidence":[{"kind":"row","id":"IMM-0000812"}],"review_status":"pending"},
    {"symptom_id":"SYM-...","span":"tired","term":"fatigue","snomed_code":"84229001","classification":"EXPECTED",
     "reason":"Listed side effect of Moderna (CVX 207); dose 2026-10-28 is within the 14-day window",
     "evidence":[{"kind":"known_effect","id":"KE-207-fatigue","source_url":"..."},{"kind":"row","id":"IMM-0000812"}],"review_status":"not_required"}],
   "audit_seq":40}
  ```
  Also returned: top-level `urgent` (bool) and `urgent_advice` (fixed safety text, null unless urgent), and `urgent` on each symptom.
  Red-flag symptoms are found by `app/clinical/red_flags.py` in the extracted terms and in the raw text (§8).

### Oversight (Dev B)
- `GET /review/queue` → `{"items":[{"item_id":"SYM-...|SEN-...","kind":"symptom|sentence","patient_id":"...","text":"...","reason":"...","evidence":[...],"created_at":"..."}]}`
  Each item also has `priority` (`urgent|normal`); urgent items come first, newest first within each group.
- `POST /review/{item_id}` body `{"decision":"approve|reject","reviewer":"Dr. Weber","note":""}` → `{"ok":true,"audit_seq":41}`

### Research (Dev C; pool endpoints read Dev A's views)
- `GET /pool/rare` → `{"k":5,"items":[{"term":"blurred vision","exposure_label":"Moderna (CVX 207)","age_band":"40-49","sex":"F","n_reports":"<5","first_month":"2026-11"}]}`
- `POST /research/ask` body `{"question":"...","sql":null}` (`sql` optional: researcher-written SQL, same guard) →
  ```json
  {"ask_id":"ASK-...","question":"...","sql":"SELECT ...","guard":{"ok":true,"violations":[]},
   "columns":["age_band","n_exposed","n_hypertension","rate_pct"],"rows":[["40-49","212","19","9.0"]],"suppressed_cells":2,
   "sufficiency":{"verdict":"SUPPORTED|CONDITIONAL|NOT_SUPPORTED","n":412,"notes":["Association only, not causation","2 cells under k=5 suppressed"]},
   "summary":[{"text":"Among vaccinated patients aged 40-49, 9.0% had a hypertension onset within 90 days (19 of 212).","cells":[[0,"rate_pct"],[0,"n_hypertension"],[0,"n_exposed"]],"status":"verified|needs_review"}],
   "mode":"llm|template","audit_seq":55}
  ```
  Blocked query → `guard.ok=false`, no rows, `sufficiency.verdict="NOT_SUPPORTED"`, audit `ask.blocked`. Cells are strings because of `"<5"`.
  Also returned: `mode` may be `"sql"` (researcher SQL), `rationale` (LLM's reason or null), `template` (template key or null),
  each summary item has `reasons` (critic findings). `sufficiency.n` is `null` when the total is under k=5.
- `GET /research/ask/templates` → `{"templates":[{"key":"hypertension_after_moderna","question":"..."}]}` (the stub-safe demo questions)
- `POST /research/graph/build` body `{"topic":"covid_vaccine_safety","max_papers":60,"inject_fabricated_quote":false}` (`true` plants PL5) → `{"run_id":"KG-...","papers":60,"candidate_edges":180,"accepted":120,"rejected":60,"audit_seq":60}`
- `GET /research/graph?concept=CVX:207&depth=1&include_rejected=false` (latest build only; adds `"run_id"`) →
  ```json
  {"nodes":[{"node_id":"CVX:207","type":"concept","label":"SARS-COV-2 mRNA vaccine (Moderna)","code_system":"CVX","pool_patients":"812"},
            {"node_id":"PMID:12345678","type":"paper","label":"Title ...","year":2023}],
   "edges":[{"edge_id":"EDG-...","src":"CVX:207","dst":"SNOMED:59621000","relation":"ASSOCIATED_WITH",
     "quote":"exact sentence from the abstract","paper":{"paper_id":"PMID:12345678","doi":"10....","title":"...","year":2023,"url":"https://europepmc.org/article/MED/12345678"},
     "critic":{"status":"PASS","reasons":[]},
     "sanity":{"literature":"CONSISTENT|CONTESTED|SINGLE_SOURCE","support_count":3,"contradict_count":1,
               "pool":"OBSERVED|NOT_OBSERVED|UNTESTABLE","pool_evidence":{"sql":"...","exposed_rate":"9.0","baseline_rate":"6.1","n_exposed":"412"}},
     "status":"ACCEPTED"},
    {"edge_id":"CIT-...","src":"PMID:23456789","dst":"PMID:12345678","relation":"CITES"}]}
  ```
  Additions: concept nodes carry `free` (FREE: node, shown grey) and `known`; `sanity.support_years` = `{"oldest":2021,"newest":2024}` or null;
  `pool_evidence` also has `sql_source`, `exposure_codes`, `n_unexposed`, `synthetic:true`, `note`, or a `reason` when UNTESTABLE.
  Deterministic `IS_A` edges (`{"edge_id":"ISA-CVX:207-CVX:213","src":"CVX:207","dst":"CVX:213","relation":"IS_A","source":"ontology"}`)
  link a vaccine to "COVID-19 vaccine (any)" (CVX 213), which papers use when they don't name the product.
- `GET /research/edges/{edge_id}` → one edge (shape above) plus `"lineage":[LineageEdge]` and `"run_id"`

### Governance (Dev B)
- `GET /lineage/{id}` → `{"id":"SEN-...","type":"sentence","chain":[{"id":"FCT-...","type":"fact","transform":"facts.sql:lab_trend","agent":null,"model":null,"prompt_hash":null,"depth":1},{"id":"OBS-0004411","type":"curated.observations","transform":"load:synthea","depth":2}],"producer":{"agent":"generator","model":"...","prompt_hash":"..."}}`
- `GET /audit?limit=100` → `[{"seq":1,"event_ts":"...","actor":"...","action_type":"...","subject":"...","payload":{},"prev_hash":"...","row_hash":"..."}]`
- `GET /audit/verify` → `{"valid":true,"length":57,"broken_at":null}`
- `POST /evals/run?patients=10` → runs every metric, stores one row per metric in `evals.runs`, audits `eval.completed`; same shape as below plus `audit_seq`. Summary metrics run the pipeline without persisting (no review-queue items).
- `GET /evals/latest` → `{"eval_id":"EVAL-...","created_at":"...","metrics":[{"name":"injected_error_catch_rate","value":1.0},{"name":"sentence_support_rate","value":0.97},{"name":"symptom_classification_accuracy","value":1.0},{"name":"unsafe_query_block_rate","value":1.0},{"name":"fabricated_quote_rejected","value":1.0},{"name":"audit_chain_valid","value":1.0}],"details":[{"name":"...", ...}]}`. `value` is null when a metric couldn't be measured; its detail has a `note` saying why

## 8. Decision rules (deterministic; the LLM never decides)

**Summary sentences:** critic FLAG or verifier ≠ SUPPORTED → `needs_review` (queue) and audit `sentence.flagged`. LLM refusal or error → `needs_review`, never a silent OK.
**Critic checks (summary):** every `fact_id` exists for this patient · every number in the text appears in a cited fact (±0.1, unit-aware) · every date/month matches a cited fact · no banned phrases for the audience (§8a) · no medical term that isn't in the cited facts.

**§8a Banned in patient text:** "you have", "you may have", "you seem", "you might", "diagnos", "suffer", "disease" (unless in a cited fact label), "should take", "stop taking", "increase", "decrease" (as advice), any dose. Physician text: "you should", "recommend", "consider prescribing", "must".

**Red flags** (`app/clinical/red_flags.py`, deterministic): chest pain, shortness of breath, palpitations, fainting, seizure, facial/throat swelling,
confusion, one-sided weakness, coughing blood, self-harm thoughts. A red flag leaves the classification unchanged, forces `review_status=pending`,
prefixes the reason with `URGENT: `, puts the item first in the queue and returns the fixed `urgent_advice` (112 / 116 117) to the patient.
Red flags the extractor missed are added from the raw text (simple negations like "no chest pain" are skipped).

**Symptom classification** (in this order): matches `ref.known_effects` for a product the patient received within `window_days` → `EXPECTED` · matches a condition/observation in the patient's record in the last 365 days → `IN_RECORD` · mapped to vocab but neither → `NEW` (pending) · not mapped → `UNMAPPED` (pending).

**Ask the data sufficiency:** guard fails → `NOT_SUPPORTED` · total n < 20 → `NOT_SUPPORTED` · any cell < 5 suppressed, or no comparison group, or it's observational (always) → `CONDITIONAL` with notes · otherwise `SUPPORTED`. Summaries may not use causal words ("causes", "leads to", "results in", "proves", "because of").

**Graph edges:** critic FAIL → `REJECTED` (kept for audit and evals, hidden by default). PASS → `ACCEPTED` with sanity labels. Sanity never deletes; it labels.

## 9. Audit hash chain

```
payload_canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
row_hash = sha256(prev_hash + "|" + event_ts_iso + "|" + actor + "|" + action_type + "|" + subject + "|" + payload_canonical)
genesis prev_hash = "0" * 64
```
Action types: `data.loaded`, `summary.generated`, `sentence.flagged`, `report.submitted`, `symptom.flagged`, `review.decision`,
`ask.answered`, `ask.blocked`, `kg.built`, `edge.accepted`, `edge.rejected`, `eval.completed`.

## 10. Planted ground truth (for demo and evals)

| ID | What | Where | Caught by |
|---|---|---|---|
| PL1 | `inject_error=true` changes one number in one summary sentence | Dev B generator | summary critic |
| PL2 | Synthetic signal: extra hypertension onsets within 90 days after CVX 207 in patients ≥ 40 (`origin='seed_signal'`) | `data/seed_signal.py` | Ask the data + A3 pool check |
| PL3 | ~300 synthetic patient reports: mostly listed side effects, plus a few NEW symptoms (blurred vision, tinnitus) | `data/seed_signal.py` | symptom classifier |
| PL4 | 5 unsafe questions (ask for names, raw rows, `DELETE`, non-pool tables, tiny cohort) | `evals.planted` | SQL guard / k-anon |
| PL5 | A fabricated quote added to one candidate edge | Dev C test | A2 critic |

PL2 is fake by design. The UI and the pitch must call it a **planted synthetic signal**, never a finding about real vaccines.

## 11. Environment variables

```
EXASOL_DSN=<host:8563>  EXASOL_USER=sys  EXASOL_PASSWORD=...     # unset → DuckDB at data/trustlens.duckdb
LLM_PROVIDER=bedrock|anthropic|stub  AWS_REGION=eu-central-1  ANTHROPIC_API_KEY=...
ANON_SALT=<random string, same for the whole team>
SYNTHEA_CSV_DIR=data/synthea/csv
NEXT_PUBLIC_API_BASE=http://localhost:8000
```
Never commit secrets. `.env` is git-ignored.

## 12. Milestones (H = hours from start, 20 h total)

Full checklist with owners: **`docs/milestones.md`**.

| Milestone | Window | Exit test (must pass in Swagger or curl) |
|---|---|---|
| **M0 Foundation** | H0–H2 | `/health` shows DB + LLM; Synthea loaded; audit append + verify works |
| **M1 Evidence-backed summaries** | H2–H6 | Patient and physician summary for any patient; every sentence cites facts → rows; `inject_error` gets flagged |
| **M2 Symptom loop + review** | H5–H9 | Report → classified; NEW goes to queue; approve → appears in `/pool/rare` |
| **M3 Researcher core** | H2–H11 | Ask the data answers 5 demo questions with SQL + verdict and blocks the 5 unsafe ones; graph built from ≥ 50 papers with cited edges |
| **🔒 MVP freeze** | **H11** | Full demo path works through Swagger. No new backend features after this, only fixes |
| **M4 Minimal UI** | H11–H16 | Patient, physician, review, researcher (graph + ask + rare) screens on the live API |
| **M5 Proof** | H14–H17 | `/evals/latest` real numbers; tamper demo for audit chain; lineage drawer |
| **M6 Demo** | H17–H20 | 3 rehearsals, backup video, 5 slides |

If a milestone slips, cut scope inside it (stub mode, templates, fewer papers). **Never** skip lineage or audit to save time.

## 13. Demo script (3 minutes, target)

1. **Hook (15 s):** "Would you trust an AI with your health? Only if you can check it."
2. **Patient (40 s):** simple overview, click a sentence → the lab rows. Report "tired, headache, blurred vision": two recorded, one flagged.
3. **Physician (35 s):** same patient with codes and lineage. Toggle `inject_error`: the critic flags it. Approve the blurred-vision report in the queue.
4. **Researcher (60 s):** graph around Moderna (CVX 207): an edge with quote + paper link + "contested" label. Ask "Is hypertension onset more common after the Moderna vaccine in patients over 40?" → SQL, suppressed cells, "association only", planted signal visible. Rare cases now show blurred vision.
5. **Proof (30 s):** Verify chain → valid; edit one row → broken at #N. Eval numbers. Say where it runs as the top bar shows it (claim "in the EU" only when it shows "(EU)").

## 14. Working agreements

- Contracts in §6–§9 change only by editing this file in the same PR and telling the team.
- Backend first. Until H11 nobody writes UI code; Swagger is the UI.
- Stub mode must always work (`LLM_PROVIDER=stub`), so the demo can't die on a missing key.
- Deterministic beats LLM. The LLM extracts, drafts and phrases; SQL and rules decide.
- Prompts live in `backend/app/prompts/*.md`; their sha256 is the `prompt_hash`.
- Synthetic data only. Planted rows are always labelled `origin='seed_signal'`.
