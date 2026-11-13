-- research.* tables (shared §6). Dev C owns them; Dev A can fold this file into db/schema.sql.
-- Portable between Exasol and DuckDB: no reserved words, no vendor types.
CREATE SCHEMA IF NOT EXISTS research;

CREATE TABLE IF NOT EXISTS research.papers (
  paper_id      VARCHAR(40),
  pmid          VARCHAR(20),
  doi           VARCHAR(200),
  title         VARCHAR(2000),
  journal       VARCHAR(500),
  pub_year      INTEGER,
  abstract_text VARCHAR(2000000),
  source_url    VARCHAR(300),
  query         VARCHAR(500),
  fetched_at    TIMESTAMP
);

CREATE TABLE IF NOT EXISTS research.edges (
  edge_id            VARCHAR(60),
  run_id             VARCHAR(60),
  src_id             VARCHAR(200),
  dst_id             VARCHAR(200),
  relation           VARCHAR(40),
  quote              VARCHAR(10000),
  paper_id           VARCHAR(40),
  critic_status      VARCHAR(10),
  critic_reasons     VARCHAR(10000),
  lit_status         VARCHAR(20),
  support_count      INTEGER,
  contradict_count   INTEGER,
  pool_status        VARCHAR(20),
  pool_evidence_json VARCHAR(100000),
  status             VARCHAR(20),
  created_at         TIMESTAMP
);

CREATE TABLE IF NOT EXISTS research.citations (
  edge_id         VARCHAR(80),
  citing_paper_id VARCHAR(40),
  cited_paper_id  VARCHAR(40)
);

CREATE TABLE IF NOT EXISTS research.asks (
  ask_id           VARCHAR(60),
  question         VARCHAR(5000),
  sql_text         VARCHAR(100000),
  guard_ok         BOOLEAN,
  guard_violations VARCHAR(10000),
  n_rows           INTEGER,
  suppressed_cells INTEGER,
  verdict          VARCHAR(20),
  summary_json     VARCHAR(2000000),
  mode             VARCHAR(20),
  created_at       TIMESTAMP
);
