-- Audit tamper demo (shared §2 point 6, M5). Rewrites history the way an insider with database access could:
-- the latest clinician review decision is flipped (approve <-> reject) directly in gov.audit_events, without
-- recomputing its hash. GET /audit/verify then reports {"valid": false, "broken_at": <that seq>}.
--
-- Run (from backend/):  python -m app.db run scripts/tamper.sql      (paths are relative to the repo root)
-- Restore:              run the same script again (it swaps back), then /audit/verify is valid again.
-- DuckDB: stop the API first (one process per DuckDB file), run, start the API. Exasol: run it while the API is up,
-- or paste the UPDATE into any SQL client (EXAplus, DBeaver) for the live "edit one row" moment.
UPDATE gov.audit_events
SET payload_json = CASE
        WHEN payload_json LIKE '%"decision":"approve"%'
            THEN REPLACE(payload_json, '"decision":"approve"', '"decision":"reject"')
        ELSE REPLACE(payload_json, '"decision":"reject"', '"decision":"approve"')
    END
WHERE seq = (SELECT MAX(seq) FROM gov.audit_events WHERE action_type = 'review.decision');
