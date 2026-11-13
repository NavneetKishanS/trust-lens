-- Named pool queries for the research agents (Dev A). They read pool.* only, like Ask the data.


-- name: exposure_outcome_rate
-- For the A3 sanity agent: is <outcome> more common within <window> after <exposure> than in a comparable window
-- for people never exposed?
--
-- Params: :exposure_code   bare CVX or RxNorm code, e.g. '207'   (research/sanity.py may rewrite
--                           "concept_code = :exposure_code" into an IN list for a vaccine class)
--         :outcome_code    bare SNOMED code, e.g. '59621000'
--         :window_days     e.g. 90
-- Returns one row: n_exposed, n_outcome_exposed, n_unexposed, n_outcome_unexposed (true counts; the caller applies k=5).
--
-- Method (simple on purpose; the pool has months, not dates):
--   * Month index = year * 12 + month. Window = ceil(window_days / 30) months, counted inclusively from the anchor
--     month, so an onset in the anchor month itself counts.
--   * Population: adults, i.e. people whose current age band is 20 or older (the pool has no age at an arbitrary month).
--   * Exposed: adults with the exposure as an immunization or a medication start. Anchor = month of the first exposure.
--   * Unexposed: adults who never had the exposure. Each gets a pseudo-random anchor month inside the period in which
--     exposures happened (first to last exposure month), derived from two hex digits of their pseudo_id. That keeps
--     calendar time comparable between the groups and is deterministic.
--   * Prevalent cases are excluded from both groups: anyone whose first outcome onset is before their anchor month.
--   * Outcome: the first onset of the outcome falls in [anchor, anchor + window].
-- Observational, unadjusted (no matching on age, sex or other conditions): association only, never causation.
WITH params AS (
    SELECT CAST(CEIL(:window_days / 30.0) AS INTEGER) AS w
),
adults AS (
    SELECT pseudo_id FROM pool.patients WHERE age_band NOT IN ('0-9', '10-19')
),
exposure_events AS (
    SELECT pseudo_id, imm_month AS m FROM pool.immunizations WHERE concept_code = :exposure_code
    UNION ALL
    SELECT pseudo_id, start_month AS m FROM pool.medications WHERE concept_code = :exposure_code
),
exposed AS (
    SELECT e.pseudo_id,
           MIN(CAST(SUBSTR(e.m, 1, 4) AS INTEGER) * 12 + CAST(SUBSTR(e.m, 6, 2) AS INTEGER)) AS anchor_idx
    FROM exposure_events e
    JOIN adults a ON a.pseudo_id = e.pseudo_id
    WHERE e.m IS NOT NULL
    GROUP BY e.pseudo_id
),
exposure_period AS (
    SELECT MIN(anchor_idx) AS first_idx, MAX(anchor_idx) - MIN(anchor_idx) + 1 AS n_months FROM exposed
),
unexposed AS (
    SELECT a.pseudo_id,
           p.first_idx + MOD((INSTR('0123456789abcdef', SUBSTR(a.pseudo_id, 6, 1)) - 1) * 16
                             + (INSTR('0123456789abcdef', SUBSTR(a.pseudo_id, 7, 1)) - 1), p.n_months) AS anchor_idx
    FROM adults a
    CROSS JOIN exposure_period p
    WHERE p.first_idx IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM exposed x WHERE x.pseudo_id = a.pseudo_id)
),
first_outcome AS (
    SELECT pseudo_id,
           MIN(CAST(SUBSTR(onset_month, 1, 4) AS INTEGER) * 12 + CAST(SUBSTR(onset_month, 6, 2) AS INTEGER)) AS onset_idx
    FROM pool.conditions
    WHERE concept_code = :outcome_code AND onset_month IS NOT NULL
    GROUP BY pseudo_id
),
cohort AS (
    SELECT 1 AS exposed, pseudo_id, anchor_idx FROM exposed
    UNION ALL
    SELECT 0 AS exposed, pseudo_id, anchor_idx FROM unexposed
),
at_risk AS (
    SELECT c.exposed,
           CASE WHEN o.onset_idx BETWEEN c.anchor_idx AND c.anchor_idx + pr.w THEN 1 ELSE 0 END AS has_outcome
    FROM cohort c
    CROSS JOIN params pr
    LEFT JOIN first_outcome o ON o.pseudo_id = c.pseudo_id
    WHERE o.onset_idx IS NULL OR o.onset_idx >= c.anchor_idx
)
SELECT COALESCE(SUM(CASE WHEN exposed = 1 THEN 1 ELSE 0 END), 0)           AS n_exposed,
       COALESCE(SUM(CASE WHEN exposed = 1 THEN has_outcome ELSE 0 END), 0) AS n_outcome_exposed,
       COALESCE(SUM(CASE WHEN exposed = 0 THEN 1 ELSE 0 END), 0)           AS n_unexposed,
       COALESCE(SUM(CASE WHEN exposed = 0 THEN has_outcome ELSE 0 END), 0) AS n_outcome_unexposed
FROM at_risk;
