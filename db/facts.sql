-- TrustLens per-patient facts (Dev A). Shared contract §6 clinical.facts, Dev A context §8.
--
-- Each '-- name: <block>' is one SELECT with parameter :patient_id. Every row is one fact:
--   kind            LAB_TREND | CONDITION | MEDICATION | IMMUNIZATION | ENCOUNTER | CAREPLAN | ALLERGY | NEXT_STEP
--   source_row_ids  comma-separated curated row IDs the fact was computed from
--   all other columns are the fact's data. A double underscore nests: latest__value -> {"latest": {"value": ...}}.
--   NULL values are dropped; a nested object whose fields are all NULL becomes null.
-- app/factsql.py runs the blocks and packs the data columns into data_json (Exasol has no JSON constructor,
-- so building JSON in SQL would not be portable).
--
-- Numbers are rounded here the way they should be written: integers for mg/dL, otherwise 1 decimal.
-- Dates are 'YYYY-MM-DD'. "Today" is CURRENT_DATE. Lab ranges are demo ranges, not clinical advice.
-- Portable SQL only (DuckDB + Exasol): no vendor functions, no '' (Exasol treats it as NULL).


-- name: lab_trend
-- Per LOINC in ref.lab_ranges: latest and previous value, flag vs range, direction. Sources: both OBS rows.
WITH obs AS (
    SELECT o.row_id, o.concept_code, o.obs_date,
           r.name, r.units, r.low, r.high, r.plain_name,
           CASE WHEN r.units = 'mg/dL' THEN ROUND(o.value_num, 0) ELSE ROUND(o.value_num, 1) END AS value_r,
           ROW_NUMBER() OVER (PARTITION BY o.concept_code ORDER BY o.obs_date DESC, o.row_id DESC) AS rn
    FROM curated.observations o
    JOIN ref.lab_ranges r ON r.loinc = o.concept_code AND r.units = o.units
    WHERE o.patient_id = :patient_id
      AND o.value_num IS NOT NULL
),
flagged AS (
    SELECT row_id, concept_code, obs_date, name, units, low, high, plain_name, value_r, rn,
           CASE WHEN value_r < low THEN 'LOW' WHEN value_r > high THEN 'HIGH' ELSE 'NORMAL' END AS flag
    FROM obs
    WHERE rn <= 2
)
SELECT 'LAB_TREND'                                   AS kind,
       l.concept_code                                AS loinc,
       l.name                                        AS name,
       l.units                                       AS units,
       l.plain_name                                  AS plain_name,
       CASE WHEN l.low > 0 THEN l.low END            AS range__low,    -- 0 = no lower limit
       CASE WHEN l.high < 999 THEN l.high END        AS range__high,   -- 999 = no upper limit
       l.value_r                                     AS latest__value,
       CAST(l.obs_date AS VARCHAR(10))               AS latest__date,
       l.flag                                        AS latest__flag,
       p.value_r                                     AS previous__value,
       CAST(p.obs_date AS VARCHAR(10))               AS previous__date,
       p.flag                                        AS previous__flag,
       CASE WHEN p.row_id IS NULL THEN NULL
            WHEN l.value_r > p.value_r THEN 'up'
            WHEN l.value_r < p.value_r THEN 'down'
            ELSE 'same' END                          AS direction,
       CASE WHEN p.row_id IS NULL THEN l.row_id ELSE l.row_id || ',' || p.row_id END AS source_row_ids
FROM flagged l
LEFT JOIN flagged p ON p.concept_code = l.concept_code AND p.rn = 2
WHERE l.rn = 1
ORDER BY l.concept_code;


-- name: condition
-- Active conditions (no stop date) and conditions resolved in the last 2 years, one fact per code
-- (latest episode). Social-circumstance findings Synthea records as conditions (employment, education,
-- housing, ...) are left out; they are not clinical problems. Physician view only.
WITH c AS (
    SELECT row_id, concept_code, code_system, description, start_date, stop_date,
           ROW_NUMBER() OVER (PARTITION BY concept_code ORDER BY start_date DESC, row_id DESC) AS rn
    FROM curated.conditions
    WHERE patient_id = :patient_id
      AND (stop_date IS NULL OR stop_date >= CURRENT_DATE - 730)
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
SELECT 'CONDITION'                              AS kind,
       code_system                              AS code_system,
       concept_code                             AS snomed,
       description                              AS description,
       CAST(start_date AS VARCHAR(10))          AS onset_date,
       CAST(stop_date AS VARCHAR(10))           AS stop_date,
       CASE WHEN stop_date IS NULL THEN 'active' ELSE 'resolved' END AS status,
       row_id                                   AS source_row_ids
FROM c
WHERE rn = 1
ORDER BY CASE WHEN stop_date IS NULL THEN 0 ELSE 1 END, start_date DESC;


-- name: medication
-- Active medications plus medications started or stopped in the last 12 months, one fact per RxNorm code
-- (latest prescription).
WITH m AS (
    SELECT row_id, concept_code, description, reason_code, reason_description,
           CAST(start_ts AS DATE) AS start_date, CAST(stop_ts AS DATE) AS stop_date,
           ROW_NUMBER() OVER (PARTITION BY concept_code ORDER BY start_ts DESC, row_id DESC) AS rn
    FROM curated.medications
    WHERE patient_id = :patient_id
      AND (stop_ts IS NULL
           OR CAST(start_ts AS DATE) >= CURRENT_DATE - 365
           OR CAST(stop_ts AS DATE) >= CURRENT_DATE - 365)
)
SELECT 'MEDICATION'                             AS kind,
       concept_code                             AS rxnorm,
       description                              AS description,
       CAST(start_date AS VARCHAR(10))          AS start_date,
       CAST(stop_date AS VARCHAR(10))           AS stop_date,
       CASE WHEN stop_date IS NULL THEN 'active' ELSE 'stopped' END AS status,
       reason_code                              AS reason__code,
       reason_description                       AS reason__description,
       row_id                                   AS source_row_ids
FROM m
WHERE rn = 1
ORDER BY CASE WHEN stop_date IS NULL THEN 0 ELSE 1 END, start_date DESC;


-- name: immunization
-- Immunizations in the last 24 months, one fact per dose. product_name is the short brand name we keep
-- in ref.known_effects (e.g. Moderna), when we have one.
SELECT 'IMMUNIZATION'                           AS kind,
       i.concept_code                           AS cvx,
       i.description                            AS description,
       k.product_name                           AS product_name,
       CAST(i.imm_date AS VARCHAR(10))          AS imm_date,
       i.row_id                                 AS source_row_ids
FROM curated.immunizations i
LEFT JOIN (SELECT product_code, MIN(product_name) AS product_name
           FROM ref.known_effects WHERE product_system = 'CVX' GROUP BY product_code) k
       ON k.product_code = i.concept_code
WHERE i.patient_id = :patient_id
  AND i.imm_date >= CURRENT_DATE - 730
ORDER BY i.imm_date DESC, i.row_id DESC;


-- name: encounter
-- The last 5 encounters.
WITH e AS (
    SELECT row_id, start_ts, encounter_class, concept_code, description, reason_code, reason_description,
           provider_name, organization_name,
           ROW_NUMBER() OVER (ORDER BY start_ts DESC, row_id DESC) AS rn
    FROM curated.encounters
    WHERE patient_id = :patient_id
)
SELECT 'ENCOUNTER'                              AS kind,
       CAST(CAST(start_ts AS DATE) AS VARCHAR(10)) AS encounter_date,
       encounter_class                          AS encounter_class,
       concept_code                             AS snomed,
       description                              AS description,
       reason_code                              AS reason__code,
       reason_description                       AS reason__description,
       provider_name                            AS provider_name,
       organization_name                        AS organization_name,
       row_id                                   AS source_row_ids
FROM e
WHERE rn <= 5
ORDER BY rn;


-- name: careplan
-- Active care plans, with the provider of the encounter that started them. Sources: CPL + ENC rows.
SELECT 'CAREPLAN'                               AS kind,
       c.concept_code                           AS snomed,
       c.description                            AS description,
       CAST(c.start_date AS VARCHAR(10))        AS start_date,
       c.reason_code                            AS reason__code,
       c.reason_description                     AS reason__description,
       e.provider_name                          AS provider_name,
       e.organization_name                      AS organization_name,
       CASE WHEN e.row_id IS NULL THEN c.row_id ELSE c.row_id || ',' || e.row_id END AS source_row_ids
FROM curated.careplans c
LEFT JOIN curated.encounters e ON e.encounter_id = c.encounter_id
WHERE c.patient_id = :patient_id
  AND c.stop_date IS NULL
ORDER BY c.start_date DESC, c.row_id;


-- name: allergy
-- Active allergies.
SELECT 'ALLERGY'                                AS kind,
       concept_code                             AS concept_code,
       description                              AS description,
       category                                 AS category,
       CAST(start_date AS VARCHAR(10))          AS start_date,
       row_id                                   AS source_row_ids
FROM curated.allergies
WHERE patient_id = :patient_id
  AND stop_date IS NULL
ORDER BY start_date DESC, row_id;


-- name: next_step
-- Rules only, no LLM:
--   CAREPLAN     every active care plan -> "Care plan <X> with <provider>"
--   DISCUSS_LAB  latest value of a lab is HIGH or LOW and the patient has had no encounter since
--                -> "Talk to your care team about your <plain_name> result from <month>"
WITH lab AS (
    SELECT o.row_id, o.concept_code, o.obs_date, r.units, r.low, r.high, r.plain_name,
           CASE WHEN r.units = 'mg/dL' THEN ROUND(o.value_num, 0) ELSE ROUND(o.value_num, 1) END AS value_r,
           ROW_NUMBER() OVER (PARTITION BY o.concept_code ORDER BY o.obs_date DESC, o.row_id DESC) AS rn
    FROM curated.observations o
    JOIN ref.lab_ranges r ON r.loinc = o.concept_code AND r.units = o.units
    WHERE o.patient_id = :patient_id
      AND o.value_num IS NOT NULL
),
latest_flagged AS (
    SELECT row_id, concept_code, obs_date, units, plain_name, value_r,
           CASE WHEN value_r < low THEN 'LOW' WHEN value_r > high THEN 'HIGH' END AS flag
    FROM lab
    WHERE rn = 1 AND (value_r < low OR value_r > high)
)
SELECT 'NEXT_STEP'                              AS kind,
       'CAREPLAN'                               AS rule_name,
       c.description                            AS careplan__description,
       CAST(c.start_date AS VARCHAR(10))        AS careplan__start_date,
       e.provider_name                          AS careplan__provider_name,
       e.organization_name                      AS careplan__organization_name,
       CAST(NULL AS VARCHAR(20))                AS lab__loinc,
       CAST(NULL AS VARCHAR(100))               AS lab__plain_name,
       CAST(NULL AS DOUBLE)                     AS lab__value,
       CAST(NULL AS VARCHAR(50))                AS lab__units,
       CAST(NULL AS VARCHAR(10))                AS lab__flag,
       CAST(NULL AS VARCHAR(10))                AS lab__date,
       CASE WHEN e.row_id IS NULL THEN c.row_id ELSE c.row_id || ',' || e.row_id END AS source_row_ids
FROM curated.careplans c
LEFT JOIN curated.encounters e ON e.encounter_id = c.encounter_id
WHERE c.patient_id = :patient_id
  AND c.stop_date IS NULL
UNION ALL
SELECT 'NEXT_STEP'                              AS kind,
       'DISCUSS_LAB'                            AS rule_name,
       CAST(NULL AS VARCHAR(500))               AS careplan__description,
       CAST(NULL AS VARCHAR(10))                AS careplan__start_date,
       CAST(NULL AS VARCHAR(200))               AS careplan__provider_name,
       CAST(NULL AS VARCHAR(200))               AS careplan__organization_name,
       l.concept_code                           AS lab__loinc,
       l.plain_name                             AS lab__plain_name,
       l.value_r                                AS lab__value,
       l.units                                  AS lab__units,
       l.flag                                   AS lab__flag,
       CAST(l.obs_date AS VARCHAR(10))          AS lab__date,
       l.row_id                                 AS source_row_ids
FROM latest_flagged l
WHERE NOT EXISTS (
    SELECT 1 FROM curated.encounters e2
    WHERE e2.patient_id = :patient_id
      AND CAST(e2.start_ts AS DATE) > l.obs_date
);
