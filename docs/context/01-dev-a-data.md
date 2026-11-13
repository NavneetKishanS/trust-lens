# Dev A — Data Platform: Exasol, Synthea, Facts SQL, Anonymised Pool

> Read `00-shared.md` first (v2). This file covers only your slice. Your milestone tasks are tagged **[M0]**, **[M1]**…

## 1. Mission

Own everything below the API. Every AI sentence in TrustLens is only as trustworthy as the SQL facts you compute and
the anonymised views you expose. Keep the SQL readable; the jury may open it.

## 2. Deliverables

| Milestone | Deliverable | By | Unblocks |
|---|---|---|---|
| M0 | Exasol Personal launching on AWS (runs in background) | H0 start | — |
| M0 | Synthea CSVs generated (or Kaggle fallback) into `data/synthea/csv/` | H1 | everyone |
| M0 | `db/schema.sql` (all §6 tables) + `backend/app/db.py` + `backend/app/load.py` loading curated, DuckDB first | H2 | B, C |
| M1 | `ref.lab_ranges` + `db/facts.sql` (all fact kinds) | H4 | B's summaries |
| M2 | `ref.known_effects`, `ref.symptom_vocab` | H5 | B's symptom intake |
| M2 | `db/pool_views.sql` (anonymised views) | H6 | C's Ask the data |
| M2 | `data/seed_signal.py` (PL2 signal + PL3 reports) | H7 | demo, evals |
| M3 | `ref.concepts` (codes + synonyms) | H7 | C's graph |
| M3 | Pool test SQL for A3 sanity agent: `exposure_outcome_rate(exposure_code, outcome_code, window_days)` | H9 | C |
| M3 | Exasol live with all data; switch is only `EXASOL_DSN` | H10 | demo |
| M5 | Audit tamper demo script (`scripts/tamper.sql` edits one audit row) | H15 | demo |

## 3. Exasol setup **[M0]** (start at H0)

1. Exasol Launcher → `exasol install aws` with the team's AWS credentials, region **eu-central-1**. Docs: https://docs.exasol.com/db/latest/get_started/exasol_personal.htm, repo https://github.com/exasol/exasol-personal. Expect 10–20 min. If you abort, terminate the EC2 instances by hand.
2. Put DSN, user, password in `.env` (never commit). Check: `pyexasol` connect + `SELECT CURRENT_TIMESTAMP`.
3. Use the resources the mentors gave us for anything AWS/Exasol specific.
4. **Fallback:** if Exasol isn't up by H10, demo on DuckDB and say so honestly. Everything must run on DuckDB from H2.

## 4. Synthea data **[M0]**

Synthea needs **Java 17+** (`brew install openjdk@17` on macOS; it isn't installed on the repo owner's Mac yet).

```bash
git clone https://github.com/synthetichealth/synthea.git ~/synthea && cd ~/synthea
./run_synthea -s 42 -p 1000 --exporter.csv.export=true --exporter.fhir.export=false
# CSVs land in ./output/csv/  → copy to trustlens/data/synthea/csv/
```
If building fails or takes too long: download the Synthea CSV dataset from Kaggle
(https://www.kaggle.com/datasets/nilesh2042/synthea-electronic-health-records-ehr-dataset, Kaggle login needed) and use the same loader.
**Check the headers first** (`head -1 *.csv`); Synthea versions differ slightly (e.g. `conditions.csv` gained a `SYSTEM` column).

Check `immunizations.csv` for COVID-19 vaccine codes (CVX 207 Moderna, 208 Pfizer). If none are present, `seed_signal.py`
adds labelled immunization rows for a subset of adults (`origin='seed_signal'`).

## 5. Load **[M0]**: `python -m app.load --reset`

- Create schemas `raw, curated, ref, clinical, community, pool, research, gov, evals`.
- Read each CSV, rename columns to snake_case without reserved words (shared §6), **drop identifying columns**
  (SSN, DRIVERS, PASSPORT, ADDRESS, LAT, LON, ZIP, BIRTHPLACE, INCOME). `display_name = FIRST + ' ' + LAST` (Synthea names are synthetic but we still keep them out of the pool).
- Assign `row_id`: sort each table by `(patient_id, date, concept_code)` and number it, `OBS-0000001`. Deterministic, so IDs are stable across reloads.
- `value_num = TRY_CAST(value_text AS DOUBLE)`.
- `source_file`, `source_line` (CSV line number) and `origin='synthea'` on every row.
- Join `provider_name` and `organization_name` into encounters from providers/organizations.
- Write one `gov.lineage_edges` row per table (`curated.<table>` ← `file:<csv>`, transform `load:synthea`) and audit `data.loaded` with row counts (use Dev B's `audit.append`, or insert directly following shared §9 if it isn't ready).
- Keep it fast: bulk insert (`pyexasol import_from_pandas` / DuckDB `read_csv_auto`).

## 6. `db.py` interface **[M0]** (Dev B and C code against this)

```python
db = get_db()                       # Exasol if EXASOL_DSN set, else DuckDB file data/trustlens.duckdb
db.query(sql, params=None) -> list[dict]
db.execute(sql, params=None) -> None
db.insert_rows(table, rows: list[dict]) -> None
db.run_script(path) -> None         # runs a .sql file
db.named_blocks(path) -> dict[str, str]   # parses '-- name: x' blocks
db.dialect -> "exasol" | "duckdb"
```
Write SQL that works on both (avoid vendor functions, or branch on `db.dialect` in one place). Use `?`-style params via a small adapter.

## 7. Reference tables

**[M1] `ref.lab_ranges`**: demo ranges for adults, **not clinical advice**. Check each LOINC exists in `observations.csv`; drop or fix codes that don't.

| loinc | name | units | low | high | plain_name |
|---|---|---|---|---|---|
| 4548-4 | Hemoglobin A1c | % | 4.0 | 5.6 | long-term blood sugar (HbA1c) |
| 2339-0 | Glucose | mg/dL | 70 | 99 | blood sugar |
| 2093-3 | Total cholesterol | mg/dL | 0 | 199 | total cholesterol |
| 18262-6 | LDL cholesterol | mg/dL | 0 | 99 | "bad" cholesterol (LDL) |
| 2085-9 | HDL cholesterol | mg/dL | 40 | 999 | "good" cholesterol (HDL) |
| 2571-8 | Triglycerides | mg/dL | 0 | 149 | blood fats (triglycerides) |
| 38483-4 | Creatinine | mg/dL | 0.6 | 1.3 | kidney value (creatinine) |
| 33914-3 | eGFR | mL/min/1.73m2 | 60 | 999 | kidney filtering (eGFR) |
| 8480-6 | Systolic blood pressure | mm[Hg] | 90 | 129 | blood pressure (top number) |
| 8462-4 | Diastolic blood pressure | mm[Hg] | 60 | 79 | blood pressure (bottom number) |
| 39156-5 | Body mass index | kg/m2 | 18.5 | 24.9 | BMI |
| 2823-3 | Potassium | mmol/L | 3.5 | 5.1 | potassium |
| 2951-2 | Sodium | mmol/L | 135 | 145 | sodium |
| 718-7 | Hemoglobin | g/dL | 12.0 | 17.5 | hemoglobin |

**[M2] `ref.known_effects`**: listed common side effects for the vaccines in our data. For Moderna (CVX 207): injection site pain, swelling,
redness, fatigue, headache, muscle pain, joint pain, chills, nausea/vomiting, fever, swollen lymph nodes in the armpit.
Take them from the official Spikevax product information (FDA prescribing information or EMA SmPC) and put **that URL** in `source_url`.
`window_days = 14` for common reactions. Add Pfizer (CVX 208) the same way if it's in the data.

**[M2] `ref.symptom_vocab`**: ~60 terms with synonyms (`fatigue; tired; exhausted; no energy`, `headache; head hurts`,
`joint pain; knee pain; aching joints`, `blurred vision; blurry eyes`, `tinnitus; ringing in ears`, `palpitations; heart racing`, …)
and a SNOMED code where you know it (leave null otherwise; don't guess codes).

**[M3] `ref.concepts`**: one row per distinct `(code_system, concept_code)` in conditions, medications, immunizations and the lab LOINCs,
`concept_id = 'SNOMED:59621000'` etc., `label = description`. Add hand synonyms for the research topics:
`CVX:207 → Moderna; mRNA-1273; Spikevax; elasomeran`, `CVX:208 → Pfizer; BNT162b2; Comirnaty`, hypertension → `high blood pressure; hypertensive`, myocarditis, etc.

## 8. Facts SQL **[M1]** (`db/facts.sql`)

`-- name: <kind>` blocks, each a SELECT with parameter `:patient_id`, returning
`kind, data_json, source_row_ids` (comma-separated row IDs). Dev B stores them in `clinical.facts` and assigns `FCT-` IDs.

| Block | Output per row |
|---|---|
| `lab_trend` | per LOINC in `ref.lab_ranges`: latest and previous value + date + flag (`LOW/NORMAL/HIGH` vs range), `direction` (`up/down/same`), `plain_name`. Sources: both OBS rows |
| `condition` | active (stop null) and resolved-in-last-2-years conditions with code + onset + stop. Physician view only |
| `medication` | active meds + meds started or stopped in the last 12 months, RxNorm code, dates |
| `immunization` | immunizations in the last 24 months, CVX code, date |
| `encounter` | last 5 encounters: date, class, description, reason, provider_name, organization_name |
| `careplan` | active care plans: description, start, reason, plus the provider of the encounter that started it |
| `allergy` | active allergies |
| `next_step` | rules only: active care plan → "Care plan *X* with *provider*"; latest lab HIGH/LOW with no encounter after it → "Talk to your care team about your *plain_name* result from *month*". Each cites its source rows |

Values in `data_json` are already rounded the way they should be written (1 decimal, or integer for mg/dL), so the critic can compare strings.

## 9. Anonymised pool **[M2]** (`db/pool_views.sql`)

- Only views, no copies. `pseudo_id` per shared §5 (hash with `ANON_SALT`; if the DB can't hash with a salt easily, materialise a `pool.id_map` table **not** readable by Ask the data).
- Dates → months (`YYYY-MM`). Birth date → 10-year age band at the event (`40-49`). No names, no Synthea UUIDs, no encounter IDs, no free text.
- `pool.symptom_reports`: from `community.symptoms` where `classification IN ('EXPECTED','IN_RECORD')` or `review_status='approved'`.
- `pool.rare_cases`: approved NEW only, grouped by term, exposure, age band, sex; the API turns `n_reports < 5` into `"<5"`.
- Write the list of views and columns into `db/pool_schema.md`. Dev C pastes it into the text-to-SQL prompt.

## 10. Planted data **[M2]** (`data/seed_signal.py`)

Deterministic (seed 42), writes straight into curated/community with `origin='seed_signal'`, and records ground truth in `evals.planted`.
- **PL2:** for vaccinated (CVX 207) patients ≥ 40, add hypertension onsets (use the hypertension SNOMED code that Synthea uses in your data) within 90 days after the dose, so the rate is clearly higher (e.g. ~9% vs ~4% baseline). Keep counts above k=5 per age band so the demo shows numbers.
- **PL3:** ~300 reports from vaccinated patients: mostly listed effects (fatigue, headache, sore arm), ~10% symptoms in the record, ~5 NEW (blurred vision, tinnitus). Insert them through Dev B's `POST /patients/{id}/reports` if it's live, so they get real classifications; otherwise insert rows and let B reclassify.
- **PL4:** 5 unsafe questions into `evals.planted` (kind `unsafe_query`).

## 11. Pool test for the A3 sanity agent **[M3]**

A named SQL block `exposure_outcome_rate` with params `exposure_code, outcome_code, window_days` returning
`n_exposed, n_outcome_exposed, n_unexposed, n_outcome_unexposed` from `pool.*` only. Unexposed baseline = adults without the exposure, same window length from a random anchor month. Simple beats perfect; document the method in a comment.

## 12. Definition of done

- [ ] `python -m app.load --reset` loads Synthea into DuckDB in < 2 min, and into Exasol with only `EXASOL_DSN` set
- [ ] Every curated row has `row_id`, `source_file`, `source_line`, `origin`
- [ ] `facts.sql` returns sensible facts for 5 random patients; every fact lists source row IDs that exist
- [ ] `SELECT * FROM pool.patients` shows no names, UUIDs or exact dates
- [ ] PL2 signal is visible with one GROUP BY on the pool
- [ ] `db/pool_schema.md` exists and matches the views

## 13. Pitfalls

- Exasol reserved words: `date`, `value`, `code`, `start`, `stop`, `system`, `type` — rename on load.
- Synthea codes vary by version. Look them up in the data; never hard-code a code you haven't seen there.
- Don't put the planted signal in without `origin='seed_signal'`. Honesty is part of the pitch.
