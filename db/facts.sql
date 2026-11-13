-- TrustLens per-patient facts (Dev A). Shared §6 clinical.facts; Dev A context §8.
--
-- Each '-- name: <kind>' block is one SELECT. Every placeholder is the patient_id (the caller passes it once per
-- placeholder, so never write a question mark in these comments). Every row is one fact:
--   kind            LAB_TREND | CONDITION | MEDICATION | IMMUNIZATION | ENCOUNTER | CAREPLAN | ALLERGY | NEXT_STEP
--   source_row_ids  comma-separated curated row IDs the fact was computed from
--   every other column is fact data; a double underscore nests (latest__value -> {"latest": {"value": ...}}).
--   NULL scalars stay as null, except opt_<name> columns, which become <name> and are left out when NULL.
--   A nested object whose fields are all NULL becomes null.
--   columns named sort_* only order the rows and are not part of the data.
-- app/factsql.py packs the data columns into data_json (Exasol has no JSON constructor, so building JSON in SQL
-- would not be portable). The data keys match the Python builders in app/clinical/facts.py, which the
-- templates and the critic read.
--
-- Rounding is done here, the way a sentence may write it: 1 decimal, integers without '.0'.
-- "Today" for a patient = the date of their latest encounter or observation (Synthea records end at generation).
-- Lab ranges are demo ranges, not clinical advice. Portable SQL only: no vendor functions, no '' literals.


-- name: lab_trend
-- Per LOINC in ref.lab_ranges (same units): latest value and the latest value from an earlier day, each
-- flagged against the range. Out-of-range results first, then newest first. Sources: both OBS rows.
WITH obs AS (
    SELECT o.row_id, o.concept_code, o.value_num, o.obs_date AS obs_ts, CAST(o.obs_date AS DATE) AS obs_day,
           r.name, r.units, r.low, r.high, r.plain_name,
           ROW_NUMBER() OVER (PARTITION BY o.concept_code ORDER BY o.obs_date DESC, o.row_id) AS rn
    FROM curated.observations o
    JOIN ref.lab_ranges r ON r.loinc = o.concept_code AND r.units = o.units
    WHERE o.patient_id = ?
      AND o.value_num IS NOT NULL
),
latest AS (
    SELECT * FROM obs WHERE rn = 1
),
previous AS (
    SELECT o.row_id, o.concept_code, o.value_num, o.obs_day, o.low, o.high,
           ROW_NUMBER() OVER (PARTITION BY o.concept_code ORDER BY o.obs_day DESC, o.rn) AS rn2
    FROM obs o
    JOIN latest l ON l.concept_code = o.concept_code
    WHERE o.obs_day < l.obs_day
)
SELECT 'LAB_TREND'                                AS kind,
       l.concept_code                             AS loinc,
       l.name                                     AS name,
       l.plain_name                               AS plain_name,
       l.units                                    AS units,
       l.low                                      AS usual_range__low,
       l.high                                     AS usual_range__high,
       ROUND(l.value_num, 1)                      AS latest__value,
       CAST(l.obs_day AS VARCHAR(10))             AS latest__date,
       CASE WHEN l.value_num < l.low THEN 'LOW' WHEN l.value_num > l.high THEN 'HIGH' ELSE 'NORMAL' END
                                                  AS latest__flag,
       ROUND(p.value_num, 1)                      AS previous__value,
       CAST(p.obs_day AS VARCHAR(10))             AS previous__date,
       CASE WHEN p.row_id IS NULL THEN NULL
            WHEN p.value_num < p.low THEN 'LOW' WHEN p.value_num > p.high THEN 'HIGH' ELSE 'NORMAL' END
                                                  AS previous__flag,
       CASE WHEN p.row_id IS NULL THEN NULL
            WHEN ROUND(l.value_num, 1) > ROUND(p.value_num, 1) THEN 'up'
            WHEN ROUND(l.value_num, 1) < ROUND(p.value_num, 1) THEN 'down'
            ELSE 'same' END                       AS opt_direction,
       CASE WHEN p.row_id IS NULL THEN l.row_id ELSE l.row_id || ',' || p.row_id END AS source_row_ids
FROM latest l
LEFT JOIN previous p ON p.concept_code = l.concept_code AND p.rn2 = 1
ORDER BY CASE WHEN l.value_num < l.low OR l.value_num > l.high THEN 0 ELSE 1 END, l.obs_day DESC, l.obs_ts DESC, l.row_id;


-- name: condition
-- Active conditions and conditions resolved in the last 2 years, one fact per code (latest episode),
-- active first. Social-circumstance findings that Synthea stores as conditions (employment, education,
-- housing, ...) are left out because they are not clinical problems. Physician view only.
WITH ref_day AS (
    SELECT COALESCE(MAX(d), CURRENT_DATE) AS d FROM (
        SELECT MAX(CAST(start_ts AS DATE)) AS d FROM curated.encounters WHERE patient_id = ?
        UNION ALL
        SELECT MAX(CAST(obs_date AS DATE)) AS d FROM curated.observations WHERE patient_id = ?
    ) x
),
c AS (
    SELECT row_id, code_system, concept_code, description, start_date, stop_date,
           ROW_NUMBER() OVER (PARTITION BY concept_code ORDER BY start_date DESC, row_id DESC) AS rn
    FROM curated.conditions
    CROSS JOIN ref_day
    WHERE patient_id = ?
      AND (stop_date IS NULL OR stop_date >= ref_day.d - 730)
      AND description NOT LIKE '%employment%'
      AND description NOT LIKE '%labor force%'
      AND description NOT LIKE 'Unemployed%'
      AND description NOT LIKE '%education%'
      AND description NOT LIKE 'Educated to%'
      AND description NOT LIKE '%school%'
      AND description NOT LIKE 'Social isolation%'
      AND description NOT LIKE 'Limited social contact%'
      AND description NOT LIKE 'Victim of%'
      AND description NOT LIKE 'Reports of violence%'
      AND description NOT LIKE 'Has a criminal record%'
      AND description NOT LIKE 'Housing unsatisfactory%'
      AND description NOT LIKE 'Homeless%'
      AND description NOT LIKE '%transportation%'
      AND description NOT LIKE 'Transport problem%'
      AND description NOT LIKE 'Refugee%'
      AND description NOT LIKE 'Serving in military service%'
      AND description NOT LIKE 'Risk activity involvement%'
      AND description NOT LIKE 'Medication review due%'
      AND description NOT LIKE '%dental filling%'
)
SELECT 'CONDITION'                                AS kind,
       COALESCE(code_system, 'SNOMED')            AS code_system,
       concept_code                               AS code,
       description                                AS description,
       CAST(start_date AS VARCHAR(10))            AS onset,
       CAST(stop_date AS VARCHAR(10))             AS resolved,
       CASE WHEN stop_date IS NULL THEN TRUE ELSE FALSE END AS active,
       row_id                                     AS source_row_ids
FROM c
WHERE rn = 1
ORDER BY CASE WHEN stop_date IS NULL THEN 0 ELSE 1 END, start_date DESC, row_id;


-- name: medication
-- Active medications plus medications started or stopped in the last 12 months, one fact per RxNorm code
-- (latest prescription), newest first.
WITH ref_day AS (
    SELECT COALESCE(MAX(d), CURRENT_DATE) AS d FROM (
        SELECT MAX(CAST(start_ts AS DATE)) AS d FROM curated.encounters WHERE patient_id = ?
        UNION ALL
        SELECT MAX(CAST(obs_date AS DATE)) AS d FROM curated.observations WHERE patient_id = ?
    ) x
),
m AS (
    SELECT row_id, concept_code, description, reason_description, start_ts,
           CAST(start_ts AS DATE) AS start_day, CAST(stop_ts AS DATE) AS stop_day,
           ROW_NUMBER() OVER (PARTITION BY concept_code ORDER BY start_ts DESC, row_id) AS rn
    FROM curated.medications
    CROSS JOIN ref_day
    WHERE patient_id = ?
      AND (stop_ts IS NULL
           OR CAST(start_ts AS DATE) >= ref_day.d - 365
           OR CAST(stop_ts AS DATE) >= ref_day.d - 365)
)
SELECT 'MEDICATION'                               AS kind,
       'RxNorm'                                   AS code_system,
       concept_code                               AS code,
       description                                AS description,
       CASE WHEN stop_day IS NULL THEN 'active' ELSE 'stopped' END AS status,
       CAST(start_day AS VARCHAR(10))             AS started,
       CAST(stop_day AS VARCHAR(10))              AS stopped,
       reason_description                         AS reason,
       row_id                                     AS source_row_ids
FROM m
WHERE rn = 1
ORDER BY start_ts DESC, row_id;


-- name: immunization
-- Immunizations in the last 24 months, one fact per dose, newest first.
WITH ref_day AS (
    SELECT COALESCE(MAX(d), CURRENT_DATE) AS d FROM (
        SELECT MAX(CAST(start_ts AS DATE)) AS d FROM curated.encounters WHERE patient_id = ?
        UNION ALL
        SELECT MAX(CAST(obs_date AS DATE)) AS d FROM curated.observations WHERE patient_id = ?
    ) x
)
SELECT 'IMMUNIZATION'                             AS kind,
       'CVX'                                      AS code_system,
       i.concept_code                             AS code,
       i.description                              AS description,
       CAST(CAST(i.imm_date AS DATE) AS VARCHAR(10)) AS "date",
       CASE WHEN i.concept_code IN ('207', '208', '210', '212', '213', '217', '218', '219', '221', '228', '229', '300')
            THEN TRUE ELSE FALSE END              AS covid_vaccine,
       i.row_id                                   AS source_row_ids
FROM curated.immunizations i
CROSS JOIN ref_day
WHERE i.patient_id = ?
  AND CAST(i.imm_date AS DATE) >= ref_day.d - 730
ORDER BY i.imm_date DESC, i.row_id;


-- name: encounter
-- The last 5 encounters, newest first.
WITH e AS (
    SELECT row_id, start_ts, encounter_class, concept_code, description, reason_description,
           provider_name, organization_name,
           ROW_NUMBER() OVER (ORDER BY start_ts DESC, row_id) AS rn
    FROM curated.encounters
    WHERE patient_id = ?
)
SELECT 'ENCOUNTER'                                AS kind,
       CAST(CAST(start_ts AS DATE) AS VARCHAR(10)) AS "date",
       encounter_class                            AS encounter_class,
       concept_code                               AS code,
       description                                AS description,
       reason_description                         AS reason,
       provider_name                              AS provider,
       organization_name                          AS organization,
       row_id                                     AS source_row_ids
FROM e
WHERE rn <= 5
ORDER BY rn;


-- name: careplan
-- Active care plans with the provider of the encounter that started them, newest first. Sources: CPL + ENC.
SELECT 'CAREPLAN'                                 AS kind,
       'SNOMED'                                   AS code_system,
       c.concept_code                             AS code,
       c.description                              AS description,
       CAST(c.start_date AS VARCHAR(10))          AS started,
       c.reason_description                       AS reason,
       e.provider_name                            AS provider,
       e.organization_name                        AS organization,
       CASE WHEN e.row_id IS NULL THEN c.row_id ELSE c.row_id || ',' || e.row_id END AS source_row_ids
FROM curated.careplans c
LEFT JOIN curated.encounters e ON e.encounter_id = c.encounter_id
WHERE c.patient_id = ?
  AND c.stop_date IS NULL
ORDER BY c.start_date DESC, c.row_id;


-- name: allergy
-- Active allergies, newest first.
SELECT 'ALLERGY'                                  AS kind,
       'SNOMED'                                   AS code_system,
       concept_code                               AS code,
       description                                AS description,
       category                                   AS category,
       CAST(start_date AS VARCHAR(10))            AS since,
       row_id                                     AS source_row_ids
FROM curated.allergies
WHERE patient_id = ?
  AND stop_date IS NULL
ORDER BY start_date DESC, row_id;


-- name: next_step
-- Rules only; the text is fixed here so the LLM can't turn it into advice.
--   out_of_range_lab_without_later_visit: the latest value of a lab is out of range and there is no visit
--       after that day -> "Talk to your care team about your <plain_name> result from <Month YYYY>."
--   active_care_plan: every active care plan -> "Keep following your care plan "<X>" with <provider>."
WITH obs AS (
    SELECT o.row_id, o.concept_code, o.value_num, o.obs_date AS obs_ts, CAST(o.obs_date AS DATE) AS obs_day,
           r.low, r.high, r.plain_name,
           ROW_NUMBER() OVER (PARTITION BY o.concept_code ORDER BY o.obs_date DESC, o.row_id) AS rn
    FROM curated.observations o
    JOIN ref.lab_ranges r ON r.loinc = o.concept_code AND r.units = o.units
    WHERE o.patient_id = ?
      AND o.value_num IS NOT NULL
),
last_visit AS (
    SELECT MAX(CAST(start_ts AS DATE)) AS d FROM curated.encounters WHERE patient_id = ?
),
lab AS (
    SELECT o.row_id, o.concept_code, o.obs_ts, o.obs_day, o.plain_name,
           CASE EXTRACT(MONTH FROM o.obs_day)
                WHEN 1 THEN 'January' WHEN 2 THEN 'February' WHEN 3 THEN 'March' WHEN 4 THEN 'April'
                WHEN 5 THEN 'May' WHEN 6 THEN 'June' WHEN 7 THEN 'July' WHEN 8 THEN 'August'
                WHEN 9 THEN 'September' WHEN 10 THEN 'October' WHEN 11 THEN 'November' ELSE 'December' END
           || ' ' || CAST(EXTRACT(YEAR FROM o.obs_day) AS VARCHAR(4)) AS month_text
    FROM obs o
    CROSS JOIN last_visit v
    WHERE o.rn = 1
      AND (o.value_num < o.low OR o.value_num > o.high)
      AND (v.d IS NULL OR v.d <= o.obs_day)
)
SELECT 'NEXT_STEP'                                AS kind,
       'out_of_range_lab_without_later_visit'     AS rule,
       CAST(obs_day AS VARCHAR(10))               AS "date",
       'Talk to your care team about your ' || plain_name || ' result from ' || month_text || '.' AS text,
       row_id                                     AS source_row_ids,
       0                                          AS sort_group,
       CAST(obs_day AS VARCHAR(10))               AS sort_day,
       CAST(obs_ts AS VARCHAR(30))                AS sort_ts,
       row_id                                     AS sort_key
FROM lab
UNION ALL
SELECT 'NEXT_STEP'                                AS kind,
       'active_care_plan'                         AS rule,
       CAST(c.start_date AS VARCHAR(10))          AS "date",
       'Keep following your care plan "' || c.description || '"'
           || CASE WHEN e.provider_name IS NULL THEN '.' ELSE ' with ' || e.provider_name || '.' END AS text,
       CASE WHEN e.row_id IS NULL THEN c.row_id ELSE c.row_id || ',' || e.row_id END AS source_row_ids,
       1                                          AS sort_group,
       CAST(c.start_date AS VARCHAR(10))          AS sort_day,
       CAST(c.start_date AS VARCHAR(30))          AS sort_ts,
       c.row_id                                   AS sort_key
FROM curated.careplans c
LEFT JOIN curated.encounters e ON e.encounter_id = c.encounter_id
WHERE c.patient_id = ?
  AND c.stop_date IS NULL
ORDER BY sort_group, sort_day DESC, sort_ts DESC, sort_key;
