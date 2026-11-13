-- Patient symptom reports (shared §6 "community"). Written by Dev B for M2; Dev A may fold this into schema.sql.
-- Portable between Exasol and DuckDB. JSON is stored as text.

CREATE SCHEMA IF NOT EXISTS community;

CREATE TABLE community.reports (
    report_id       VARCHAR(40)   NOT NULL,
    patient_id      VARCHAR(100)  NOT NULL,
    report_text     VARCHAR(4000) NOT NULL,
    onset_date      DATE,
    submitted_at    VARCHAR(40)   NOT NULL
);

CREATE TABLE community.symptoms (
    symptom_id      VARCHAR(40)   NOT NULL,
    report_id       VARCHAR(40)   NOT NULL,
    patient_id      VARCHAR(100)  NOT NULL,
    span            VARCHAR(500)  NOT NULL,
    term            VARCHAR(200)  NOT NULL,
    snomed_code     VARCHAR(30),
    classification  VARCHAR(20)   NOT NULL,
    reason          VARCHAR(2000) NOT NULL,
    evidence_json   VARCHAR(2000000) NOT NULL,
    exposure_code   VARCHAR(30),
    exposure_label  VARCHAR(200),
    exposure_date   DATE,
    onset_date      DATE          NOT NULL,
    review_status   VARCHAR(20)   NOT NULL,
    reviewed_by     VARCHAR(200),
    reviewed_at     VARCHAR(40),
    review_note     VARCHAR(2000),
    created_at      VARCHAR(40)   NOT NULL
);
