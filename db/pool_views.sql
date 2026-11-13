-- Anonymised research pool (Dev A). Shared §6 "pool". Created by app/load.py after curated + ref are loaded.
--
-- Rules every view follows:
--   * Only views, no copies. The only identifier is pseudo_id = 'ANON-' + 12 hex of sha256(ANON_SALT + patient_id),
--     looked up in curated.pseudo_ids (computed in Python, so the salt is never in the DB or in this file).
--   * No names, no Synthea UUIDs, no encounter IDs, no row IDs, no free text (descriptions are code labels).
--   * Dates become months ('YYYY-MM'). Birth dates become 10-year age bands at the event ('40-49'); 90 and over is '90+'.
--   * pool.* is the ONLY schema Ask the data may read. The helper objects below live in curated, so the guard
--     never lets a researcher query them.
-- Portable SQL (DuckDB + Exasol). Counts under k=5 are suppressed by the API, not here.


-- --------------------------------------------------------------------------------------------
-- Helpers (curated, not readable by Ask the data)
-- --------------------------------------------------------------------------------------------

-- One row per patient: pseudonym, demographics and the birth date as a YYYYMMDD number, so the age at any event is
-- FLOOR((event_ymd - birth_ymd) / 10000) without vendor date functions.
CREATE OR REPLACE VIEW curated.v_pool_person AS
SELECT p.patient_id,
       m.pseudo_id,
       p.sex,
       p.race,
       p.ethnicity,
       EXTRACT(YEAR FROM p.birth_date) * 10000 + EXTRACT(MONTH FROM p.birth_date) * 100
           + EXTRACT(DAY FROM p.birth_date)                                           AS birth_ymd,
       COALESCE(p.death_date, CURRENT_DATE)                                           AS last_alive_date
FROM curated.patients p
JOIN curated.pseudo_ids m ON m.patient_id = p.patient_id;


-- Symptom reports joined to their patient, with the exposure Dev B's classifier matched (community.symptoms.exposure_*).
-- Only symptoms that are fit for research: EXPECTED and IN_RECORD (recorded for statistics), and NEW symptoms a
-- clinician approved. Pending, rejected and UNMAPPED symptoms never reach the pool.
CREATE OR REPLACE VIEW curated.v_pool_symptoms AS
SELECT pp.pseudo_id,
       pp.sex,
       pp.birth_ymd,
       s.term,
       s.classification,
       s.exposure_code,
       s.exposure_label,
       s.onset_date,
       CAST(s.onset_date AS DATE) - CAST(s.exposure_date AS DATE)                     AS days_since_exposure,
       SUBSTR(r.submitted_at, 1, 7)                                                   AS report_month,
       SUBSTR(CAST(CAST(s.onset_date AS DATE) AS VARCHAR(10)), 1, 7)                  AS onset_month,
       EXTRACT(YEAR FROM s.onset_date) * 10000 + EXTRACT(MONTH FROM s.onset_date) * 100
           + EXTRACT(DAY FROM s.onset_date)                                           AS onset_ymd
FROM community.symptoms s
JOIN community.reports r ON r.report_id = s.report_id
JOIN curated.v_pool_person pp ON pp.patient_id = s.patient_id
WHERE s.classification IN ('EXPECTED', 'IN_RECORD')
   OR (s.classification = 'NEW' AND s.review_status = 'approved');


-- --------------------------------------------------------------------------------------------
-- pool views (the researcher-facing contract)
-- --------------------------------------------------------------------------------------------

-- pool.patients(pseudo_id, age_band, sex, race, ethnicity). age_band = today's age, or age at death.
CREATE OR REPLACE VIEW pool.patients AS
SELECT x.pseudo_id, b.age_band, x.sex, x.race, x.ethnicity
FROM (
    SELECT pseudo_id, sex, race, ethnicity,
           CAST(FLOOR((EXTRACT(YEAR FROM last_alive_date) * 10000 + EXTRACT(MONTH FROM last_alive_date) * 100
                       + EXTRACT(DAY FROM last_alive_date) - birth_ymd) / 10000) AS INTEGER) AS age_years
    FROM curated.v_pool_person
) x
JOIN curated.age_bands b ON b.age_years = x.age_years;


-- pool.conditions(pseudo_id, concept_code, description, onset_month, age_band_at_onset). SNOMED CT codes.
CREATE OR REPLACE VIEW pool.conditions AS
SELECT x.pseudo_id, x.concept_code, x.description, x.onset_month, b.age_band AS age_band_at_onset
FROM (
    SELECT pp.pseudo_id, c.concept_code, c.description,
           SUBSTR(CAST(c.start_date AS VARCHAR(10)), 1, 7)                           AS onset_month,
           CAST(FLOOR((EXTRACT(YEAR FROM c.start_date) * 10000 + EXTRACT(MONTH FROM c.start_date) * 100
                       + EXTRACT(DAY FROM c.start_date) - pp.birth_ymd) / 10000) AS INTEGER) AS age_years
    FROM curated.conditions c
    JOIN curated.v_pool_person pp ON pp.patient_id = c.patient_id
    WHERE c.start_date IS NOT NULL
) x
JOIN curated.age_bands b ON b.age_years = x.age_years;


-- pool.observations(pseudo_id, concept_code, description, value_num, units, obs_month). LOINC codes, numeric values
-- only (text answers such as survey responses are left out).
CREATE OR REPLACE VIEW pool.observations AS
SELECT pp.pseudo_id, o.concept_code, o.description, o.value_num, o.units,
       SUBSTR(CAST(CAST(o.obs_date AS DATE) AS VARCHAR(10)), 1, 7)                    AS obs_month
FROM curated.observations o
JOIN curated.v_pool_person pp ON pp.patient_id = o.patient_id
WHERE o.value_num IS NOT NULL;


-- pool.medications(pseudo_id, concept_code, description, start_month, stop_month). RxNorm codes; stop_month NULL = active.
CREATE OR REPLACE VIEW pool.medications AS
SELECT pp.pseudo_id, m.concept_code, m.description,
       SUBSTR(CAST(CAST(m.start_ts AS DATE) AS VARCHAR(10)), 1, 7)                    AS start_month,
       SUBSTR(CAST(CAST(m.stop_ts AS DATE) AS VARCHAR(10)), 1, 7)                     AS stop_month
FROM curated.medications m
JOIN curated.v_pool_person pp ON pp.patient_id = m.patient_id;


-- pool.immunizations(pseudo_id, concept_code, description, imm_month, age_band_at_dose). CVX codes, one row per dose.
CREATE OR REPLACE VIEW pool.immunizations AS
SELECT x.pseudo_id, x.concept_code, x.description, x.imm_month, b.age_band AS age_band_at_dose
FROM (
    SELECT pp.pseudo_id, i.concept_code, i.description,
           SUBSTR(CAST(CAST(i.imm_date AS DATE) AS VARCHAR(10)), 1, 7)                AS imm_month,
           CAST(FLOOR((EXTRACT(YEAR FROM i.imm_date) * 10000 + EXTRACT(MONTH FROM i.imm_date) * 100
                       + EXTRACT(DAY FROM i.imm_date) - pp.birth_ymd) / 10000) AS INTEGER) AS age_years
    FROM curated.immunizations i
    JOIN curated.v_pool_person pp ON pp.patient_id = i.patient_id
) x
JOIN curated.age_bands b ON b.age_years = x.age_years;


-- pool.symptom_reports(pseudo_id, term, classification, exposure_code, exposure_label, days_since_exposure,
--                      report_month). EXPECTED, IN_RECORD and approved NEW only (see curated.v_pool_symptoms).
CREATE OR REPLACE VIEW pool.symptom_reports AS
SELECT pseudo_id, term, classification, exposure_code, exposure_label, days_since_exposure, report_month
FROM curated.v_pool_symptoms;


-- pool.rare_cases(term, exposure_label, age_band, sex, n_reports, first_month). Clinician-approved NEW symptoms only,
-- already aggregated. n_reports is the true count; the API shows it as "<5" when it is under k=5.
-- age_band is the age at symptom onset; first_month is the earliest onset month.
CREATE OR REPLACE VIEW pool.rare_cases AS
SELECT x.term,
       x.exposure_label,
       b.age_band,
       x.sex,
       COUNT(*)            AS n_reports,
       MIN(x.onset_month)  AS first_month
FROM (
    SELECT term, COALESCE(exposure_label, 'no recent exposure') AS exposure_label, sex, onset_month,
           CAST(FLOOR((onset_ymd - birth_ymd) / 10000) AS INTEGER) AS age_years
    FROM curated.v_pool_symptoms
    WHERE classification = 'NEW'
) x
JOIN curated.age_bands b ON b.age_years = x.age_years
GROUP BY x.term, x.exposure_label, b.age_band, x.sex;
