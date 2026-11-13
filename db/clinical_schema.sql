-- Clinical engine tables (shared §6 "clinical"). Written by Dev B for M1; Dev A may fold this into schema.sql.
-- Portable between Exasol and DuckDB. JSON is stored as text.

CREATE SCHEMA IF NOT EXISTS clinical;

CREATE TABLE clinical.facts (
    fact_id         VARCHAR(40)   NOT NULL,
    patient_id      VARCHAR(100)  NOT NULL,
    kind            VARCHAR(20)   NOT NULL,
    data_json       VARCHAR(2000000) NOT NULL,
    source_row_ids  VARCHAR(2000000) NOT NULL,
    computed_at     VARCHAR(40)   NOT NULL
);

CREATE TABLE clinical.summaries (
    summary_id      VARCHAR(40)   NOT NULL,
    patient_id      VARCHAR(100)  NOT NULL,
    audience        VARCHAR(20)   NOT NULL,
    inject_error    BOOLEAN       NOT NULL,
    overall_status  VARCHAR(20)   NOT NULL,
    model           VARCHAR(100)  NOT NULL,
    prompt_hash     CHAR(64)      NOT NULL,
    created_at      VARCHAR(40)   NOT NULL
);

CREATE TABLE clinical.sentences (
    sentence_id     VARCHAR(40)   NOT NULL,
    summary_id      VARCHAR(40)   NOT NULL,
    sort_order      DECIMAL(9,0)  NOT NULL,
    section         VARCHAR(100)  NOT NULL,
    sentence_text   VARCHAR(4000) NOT NULL,
    fact_ids        VARCHAR(4000) NOT NULL,
    critic_status   VARCHAR(10)   NOT NULL,
    critic_reasons  VARCHAR(4000),
    verifier_status VARCHAR(20)   NOT NULL,
    verifier_reason VARCHAR(4000),
    review_status   VARCHAR(20)   NOT NULL,
    reviewed_by     VARCHAR(200),
    reviewed_at     VARCHAR(40)
);
