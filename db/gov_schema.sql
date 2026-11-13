-- Governance tables (shared §6 "gov"). Written by Dev B for M0; Dev A may fold this into schema.sql.
-- Portable between Exasol and DuckDB. event_ts is stored as an ISO string so the audit hash recomputes exactly.

CREATE SCHEMA IF NOT EXISTS gov;

CREATE TABLE gov.audit_events (
    seq           DECIMAL(18,0) NOT NULL,
    event_ts      VARCHAR(40)   NOT NULL,
    actor         VARCHAR(200)  NOT NULL,
    action_type   VARCHAR(100)  NOT NULL,
    subject       VARCHAR(200)  NOT NULL,
    payload_json  VARCHAR(2000000),
    prev_hash     CHAR(64)      NOT NULL,
    row_hash      CHAR(64)      NOT NULL
);

CREATE TABLE gov.lineage_edges (
    derived_id    VARCHAR(200)  NOT NULL,
    derived_type  VARCHAR(100)  NOT NULL,
    source_id     VARCHAR(200)  NOT NULL,
    source_type   VARCHAR(100)  NOT NULL,
    transform     VARCHAR(200),
    agent         VARCHAR(100),
    model         VARCHAR(100),
    prompt_hash   CHAR(64),
    created_at    VARCHAR(40)   NOT NULL
);

CREATE TABLE gov.llm_calls (
    call_id       VARCHAR(60)   NOT NULL,
    purpose       VARCHAR(100)  NOT NULL,
    model         VARCHAR(100)  NOT NULL,
    prompt_hash   CHAR(64)      NOT NULL,
    input_hash    CHAR(64)      NOT NULL,
    stop_reason   VARCHAR(40),
    latency_ms    DECIMAL(18,0),
    ok            BOOLEAN       NOT NULL,
    error         VARCHAR(2000),
    created_at    VARCHAR(40)   NOT NULL
);
