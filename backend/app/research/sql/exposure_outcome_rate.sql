-- Fallback for Dev A's exposure_outcome_rate (Dev A §11). sanity.py uses Dev A's block from db/*.sql when it exists.
-- Reads pool.* only. Params: :exposure_code (raw code, e.g. '207'), :outcome_code (e.g. '59621000'), :window_days.
--
-- Method (simple on purpose; the pool only has months, not dates):
--   window_months = ceil(window_days / 30)
--   exposed     = adults (age band 20+) with the exposure (immunization or medication); index month = first exposure month
--   outcome     = a condition with :outcome_code whose onset month is in [index month, index month + window_months]
--   unexposed   = adults never exposed; the same window starts at an anchor month = the most common exposure month
--                 (deterministic stand-in for a random anchor)
-- Returns one row: n_exposed, n_outcome_exposed, n_unexposed, n_outcome_unexposed.

-- name: exposure_outcome_rate
WITH params AS (
  SELECT CAST(CEIL(:window_days / 30.0) AS INTEGER) AS w
),
adults AS (
  SELECT pseudo_id FROM pool.patients WHERE age_band NOT IN ('0-9', '10-19')
),
exp_events AS (
  SELECT pseudo_id, imm_month AS m FROM pool.immunizations WHERE concept_code = :exposure_code
  UNION ALL
  SELECT pseudo_id, start_month AS m FROM pool.medications WHERE concept_code = :exposure_code
),
exposed AS (
  SELECT e.pseudo_id,
         MIN(CAST(SUBSTR(e.m, 1, 4) AS INTEGER) * 12 + CAST(SUBSTR(e.m, 6, 2) AS INTEGER)) AS idx
  FROM exp_events e JOIN adults a ON a.pseudo_id = e.pseudo_id
  WHERE e.m IS NOT NULL
  GROUP BY e.pseudo_id
),
anchor AS (
  SELECT idx FROM (SELECT idx, COUNT(*) AS c FROM exposed GROUP BY idx) t ORDER BY c DESC, idx LIMIT 1
),
onsets AS (
  SELECT pseudo_id, CAST(SUBSTR(onset_month, 1, 4) AS INTEGER) * 12 + CAST(SUBSTR(onset_month, 6, 2) AS INTEGER) AS idx
  FROM pool.conditions WHERE concept_code = :outcome_code AND onset_month IS NOT NULL
),
unexposed AS (
  SELECT a.pseudo_id FROM adults a WHERE a.pseudo_id NOT IN (SELECT pseudo_id FROM exposed)
)
SELECT
  (SELECT COUNT(*) FROM exposed) AS n_exposed,
  (SELECT COUNT(DISTINCT x.pseudo_id) FROM exposed x JOIN onsets o ON o.pseudo_id = x.pseudo_id CROSS JOIN params p
     WHERE o.idx BETWEEN x.idx AND x.idx + p.w) AS n_outcome_exposed,
  (SELECT COUNT(*) FROM unexposed) AS n_unexposed,
  (SELECT COUNT(DISTINCT u.pseudo_id) FROM unexposed u JOIN onsets o ON o.pseudo_id = u.pseudo_id CROSS JOIN anchor an CROSS JOIN params p
     WHERE o.idx BETWEEN an.idx AND an.idx + p.w) AS n_outcome_unexposed
