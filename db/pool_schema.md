# Anonymised pool: views for "Ask the data"

All data is synthetic (Synthea). Read only these views, always schema-qualified (`pool.patients`, ...).
There are no names, no patient IDs other than `pseudo_id`, no exact dates (months only, `'YYYY-MM'`) and no free text.
Counts under 5 are suppressed by the API. Observational data: associations only, never causation.

| View | Columns | Notes |
|---|---|---|
| `pool.patients` | `pseudo_id, age_band, sex, race, ethnicity` | one row per patient; `age_band` = current age (or age at death) |
| `pool.conditions` | `pseudo_id, concept_code, description, onset_month, age_band_at_onset` | SNOMED CT codes; one row per recorded episode |
| `pool.observations` | `pseudo_id, concept_code, description, value_num, units, obs_month` | LOINC codes; numeric values only |
| `pool.medications` | `pseudo_id, concept_code, description, start_month, stop_month` | RxNorm codes; `stop_month` NULL = still active |
| `pool.immunizations` | `pseudo_id, concept_code, description, imm_month, age_band_at_dose` | CVX codes; one row per dose |
| `pool.symptom_reports` | `pseudo_id, term, classification, exposure_code, exposure_label, days_since_exposure, report_month` | patient-reported symptoms: `EXPECTED`, `IN_RECORD`, and `NEW` approved by a clinician |
| `pool.rare_cases` | `term, exposure_label, age_band, sex, n_reports, first_month` | already aggregated; clinician-approved `NEW` symptoms only |

## Value formats

- `pseudo_id`: `'ANON-'` + 12 hex characters. Join views on it; never select it without aggregating.
- `age_band`, `age_band_at_onset`, `age_band_at_dose`: `'0-9'`, `'10-19'`, ..., `'80-89'`, `'90+'` (age at that event).
- Months (`onset_month`, `obs_month`, `start_month`, `stop_month`, `imm_month`, `report_month`, `first_month`): text `'YYYY-MM'`.
  Month index for windows: `CAST(SUBSTR(m, 1, 4) AS INTEGER) * 12 + CAST(SUBSTR(m, 6, 2) AS INTEGER)`.
- `sex`: `'F'` or `'M'`.
- `concept_code`: the bare code, no system prefix (`'207'`, `'59621000'`, `'4548-4'`, `'860975'`).
- `classification`: `'EXPECTED'` (listed side effect within its window), `'IN_RECORD'` (already in the patient's record), `'NEW'`.
- `exposure_code` / `exposure_label`: the vaccine or medicine the symptom was matched to, e.g. `'207'` / `'Moderna (CVX 207)'`.
- `days_since_exposure`: whole days from that dose to symptom onset.

## Codes present in the data

| Concept | Code | View |
|---|---|---|
| Moderna COVID-19 vaccine | CVX `207` | `pool.immunizations` |
| Pfizer-BioNTech COVID-19 vaccine | CVX `208` | `pool.immunizations` |
| Janssen COVID-19 vaccine | CVX `212` | `pool.immunizations` |
| Seasonal influenza vaccine | CVX `140` | `pool.immunizations` |
| Essential hypertension | SNOMED `59621000` | `pool.conditions` |
| Diabetes mellitus type 2 | SNOMED `44054006` | `pool.conditions` |
| Prediabetes | SNOMED `714628002` | `pool.conditions` |
| Metformin 500 mg ER | RxNorm `860975` | `pool.medications` |
| HbA1c | LOINC `4548-4` (%) | `pool.observations` |
| Glucose | LOINC `2339-0` (mg/dL) | `pool.observations` |
| Systolic blood pressure | LOINC `8480-6` (mm[Hg]) | `pool.observations` |
| Body mass index | LOINC `39156-5` (kg/m2) | `pool.observations` |

## Planted synthetic signal

The data contains a **planted synthetic signal** (`data/seed_signal.py`): extra hypertension onsets (SNOMED `59621000`)
within 90 days after a first Moderna dose (CVX `207`) in patients aged 40 and over. It exists to demonstrate the
system and is not a finding about any real vaccine. Say so whenever a result touches it.

## Example

```sql
-- Hypertension onset within 3 months of the first Moderna dose, by age band at that dose
WITH first_dose AS (
  SELECT pseudo_id, MIN(imm_month) AS m FROM pool.immunizations WHERE concept_code = '207' GROUP BY pseudo_id
)
SELECT i.age_band_at_dose AS age_band,
       COUNT(DISTINCT f.pseudo_id) AS n_exposed,
       COUNT(DISTINCT CASE WHEN CAST(SUBSTR(c.onset_month, 1, 4) AS INTEGER) * 12 + CAST(SUBSTR(c.onset_month, 6, 2) AS INTEGER)
                           BETWEEN CAST(SUBSTR(f.m, 1, 4) AS INTEGER) * 12 + CAST(SUBSTR(f.m, 6, 2) AS INTEGER)
                               AND CAST(SUBSTR(f.m, 1, 4) AS INTEGER) * 12 + CAST(SUBSTR(f.m, 6, 2) AS INTEGER) + 3
                      THEN f.pseudo_id END) AS n_hypertension
FROM first_dose f
JOIN pool.immunizations i ON i.pseudo_id = f.pseudo_id AND i.imm_month = f.m AND i.concept_code = '207'
LEFT JOIN pool.conditions c ON c.pseudo_id = f.pseudo_id AND c.concept_code = '59621000'
GROUP BY i.age_band_at_dose
ORDER BY 1
```
