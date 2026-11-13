-- TrustLens schema (shared contract §6). Runs on DuckDB and Exasol via app.db.run_script.
-- Portable types only. Names that are reserved in Exasol (ref, text, section, state, low, high,
-- transform) are quoted automatically by app/db.py on Exasol; keep them lowercase and unquoted here.
-- Idempotent: CREATE ... IF NOT EXISTS. `python -m app.load --reset` drops all schemas first.

CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS curated;
CREATE SCHEMA IF NOT EXISTS ref;
CREATE SCHEMA IF NOT EXISTS clinical;
CREATE SCHEMA IF NOT EXISTS community;
CREATE SCHEMA IF NOT EXISTS pool;
CREATE SCHEMA IF NOT EXISTS research;
CREATE SCHEMA IF NOT EXISTS gov;
CREATE SCHEMA IF NOT EXISTS evals;

-- ============================================================================================
-- curated: Synthea, cleaned. patient_id = Synthea UUID. Identifying columns are never loaded.
-- Every row: row_id (stable, e.g. OBS-0004411), source_file, source_line (CSV line, header = 1),
-- origin ('synthea' | 'seed_signal').
-- ============================================================================================

CREATE TABLE IF NOT EXISTS curated.patients (
    row_id            VARCHAR(20) NOT NULL,
    patient_id        VARCHAR(64) NOT NULL,
    display_name      VARCHAR(200),
    birth_date        DATE,
    death_date        DATE,
    sex               VARCHAR(10),
    race              VARCHAR(50),
    ethnicity         VARCHAR(50),
    state             VARCHAR(100),
    source_file       VARCHAR(100),
    source_line       INTEGER,
    origin            VARCHAR(20)
);

CREATE TABLE IF NOT EXISTS curated.encounters (
    row_id             VARCHAR(20) NOT NULL,
    encounter_id       VARCHAR(64),
    patient_id         VARCHAR(64) NOT NULL,
    start_ts           TIMESTAMP,
    stop_ts            TIMESTAMP,
    encounter_class    VARCHAR(50),
    concept_code       VARCHAR(50),
    description        VARCHAR(500),
    reason_code        VARCHAR(50),
    reason_description VARCHAR(500),
    provider_name      VARCHAR(200),
    organization_name  VARCHAR(200),
    source_file        VARCHAR(100),
    source_line        INTEGER,
    origin             VARCHAR(20)
);

CREATE TABLE IF NOT EXISTS curated.conditions (
    row_id        VARCHAR(20) NOT NULL,
    patient_id    VARCHAR(64) NOT NULL,
    encounter_id  VARCHAR(64),
    start_date    DATE,
    stop_date     DATE,
    code_system   VARCHAR(20),
    concept_code  VARCHAR(50),
    description   VARCHAR(500),
    source_file   VARCHAR(100),
    source_line   INTEGER,
    origin        VARCHAR(20)
);

CREATE TABLE IF NOT EXISTS curated.observations (
    row_id        VARCHAR(20) NOT NULL,
    patient_id    VARCHAR(64) NOT NULL,
    encounter_id  VARCHAR(64),
    obs_date      DATE,
    category      VARCHAR(50),
    concept_code  VARCHAR(50),
    description   VARCHAR(500),
    value_text    VARCHAR(500),
    value_num     DOUBLE,
    units         VARCHAR(50),
    value_type    VARCHAR(20),
    source_file   VARCHAR(100),
    source_line   INTEGER,
    origin        VARCHAR(20)
);

CREATE TABLE IF NOT EXISTS curated.medications (
    row_id             VARCHAR(20) NOT NULL,
    patient_id         VARCHAR(64) NOT NULL,
    encounter_id       VARCHAR(64),
    start_ts           TIMESTAMP,
    stop_ts            TIMESTAMP,
    concept_code       VARCHAR(50),
    description        VARCHAR(500),
    reason_code        VARCHAR(50),
    reason_description VARCHAR(500),
    source_file        VARCHAR(100),
    source_line        INTEGER,
    origin             VARCHAR(20)
);

CREATE TABLE IF NOT EXISTS curated.immunizations (
    row_id        VARCHAR(20) NOT NULL,
    patient_id    VARCHAR(64) NOT NULL,
    encounter_id  VARCHAR(64),
    imm_date      DATE,
    concept_code  VARCHAR(50),
    description   VARCHAR(500),
    source_file   VARCHAR(100),
    source_line   INTEGER,
    origin        VARCHAR(20)
);

CREATE TABLE IF NOT EXISTS curated.careplans (
    row_id             VARCHAR(20) NOT NULL,
    careplan_id        VARCHAR(64),
    patient_id         VARCHAR(64) NOT NULL,
    encounter_id       VARCHAR(64),
    start_date         DATE,
    stop_date          DATE,
    concept_code       VARCHAR(50),
    description        VARCHAR(500),
    reason_code        VARCHAR(50),
    reason_description VARCHAR(500),
    source_file        VARCHAR(100),
    source_line        INTEGER,
    origin             VARCHAR(20)
);

CREATE TABLE IF NOT EXISTS curated.allergies (
    row_id        VARCHAR(20) NOT NULL,
    patient_id    VARCHAR(64) NOT NULL,
    start_date    DATE,
    stop_date     DATE,
    concept_code  VARCHAR(50),
    description   VARCHAR(500),
    category      VARCHAR(50),
    source_file   VARCHAR(100),
    source_line   INTEGER,
    origin        VARCHAR(20)
);

-- Pseudonym map: pseudo_id = 'ANON-' + first 12 hex of sha256(ANON_SALT + patient_id), computed in
-- Python at load time so the salt never sits in the database or in view text.
-- Lives in curated (not pool) so Ask the data can never read it.
CREATE TABLE IF NOT EXISTS curated.pseudo_ids (
    patient_id  VARCHAR(64) NOT NULL,
    pseudo_id   VARCHAR(20) NOT NULL
);

-- Age in whole years -> 10-year band used by the pool views ('40-49'; 90 and over is '90+'). Filled by the loader.
CREATE TABLE IF NOT EXISTS curated.age_bands (
    age_years  INTEGER NOT NULL,
    age_band   VARCHAR(10) NOT NULL
);

-- ============================================================================================
-- ref: small hand-made reference tables (CSV sources in db/ref/)
-- ============================================================================================

-- Demo ranges for adults. NOT clinical advice.
CREATE TABLE IF NOT EXISTS ref.lab_ranges (
    loinc       VARCHAR(20) NOT NULL,
    name        VARCHAR(100),
    units       VARCHAR(50),
    low         DOUBLE,
    high        DOUBLE,
    plain_name  VARCHAR(100)
);

CREATE TABLE IF NOT EXISTS ref.known_effects (
    effect_id       VARCHAR(80) NOT NULL,
    product_system  VARCHAR(20),
    product_code    VARCHAR(50),
    product_name    VARCHAR(100),
    effect_term     VARCHAR(100),
    window_days     INTEGER,
    source_title    VARCHAR(300),
    source_url      VARCHAR(500)
);

CREATE TABLE IF NOT EXISTS ref.symptom_vocab (
    term         VARCHAR(100) NOT NULL,
    synonyms     VARCHAR(1000),   -- ';'-separated, includes the term itself
    snomed_code  VARCHAR(20)      -- NULL when we are not sure of the code
);

CREATE TABLE IF NOT EXISTS ref.concepts (
    concept_id    VARCHAR(80) NOT NULL,   -- e.g. SNOMED:59621000, CVX:207, RXNORM:860975, LOINC:4548-4
    code_system   VARCHAR(20),
    concept_code  VARCHAR(50),
    label         VARCHAR(500),
    synonyms      VARCHAR(2000)           -- ';'-separated
);

-- ============================================================================================
-- clinical (Dev B writes)
-- ============================================================================================
-- clinical.* and community.* are defined in db/clinical_schema.sql and db/community_schema.sql
-- (created by app.schema.ensure_schema, which app.load.create_schema also runs). One definition per table.

-- ============================================================================================
-- research (Dev C writes)
-- ============================================================================================

CREATE TABLE IF NOT EXISTS research.papers (
    paper_id       VARCHAR(40) NOT NULL,
    pmid           VARCHAR(20),
    doi            VARCHAR(200),
    title          VARCHAR(2000),
    journal        VARCHAR(500),
    pub_year       INTEGER,
    abstract_text  VARCHAR(2000000),
    source_url     VARCHAR(500),
    query          VARCHAR(1000),
    fetched_at     TIMESTAMP
);

CREATE TABLE IF NOT EXISTS research.edges (
    edge_id             VARCHAR(40) NOT NULL,
    run_id              VARCHAR(40),
    src_id              VARCHAR(100),
    dst_id              VARCHAR(100),
    relation            VARCHAR(40),
    quote               VARCHAR(4000),
    paper_id            VARCHAR(40),
    critic_status       VARCHAR(10),
    critic_reasons      VARCHAR(4000),
    lit_status          VARCHAR(20),
    support_count       INTEGER,
    contradict_count    INTEGER,
    pool_status         VARCHAR(20),
    pool_evidence_json  VARCHAR(20000),
    status              VARCHAR(20),
    created_at          TIMESTAMP
);

CREATE TABLE IF NOT EXISTS research.citations (
    edge_id          VARCHAR(40) NOT NULL,
    citing_paper_id  VARCHAR(40),
    cited_paper_id   VARCHAR(40)
);

CREATE TABLE IF NOT EXISTS research.asks (
    ask_id            VARCHAR(40) NOT NULL,
    question          VARCHAR(4000),
    sql_text          VARCHAR(20000),
    guard_ok          BOOLEAN,
    guard_violations  VARCHAR(4000),
    n_rows            INTEGER,
    suppressed_cells  INTEGER,
    verdict           VARCHAR(20),
    summary_json      VARCHAR(2000000),
    mode              VARCHAR(20),
    created_at        TIMESTAMP
);

-- ============================================================================================
-- gov (Dev B writes through audit.py / lineage.py)
-- ============================================================================================
-- gov.* is defined in db/gov_schema.sql (created by app.schema.ensure_schema).

-- ============================================================================================
-- evals (M5)
-- ============================================================================================

CREATE TABLE IF NOT EXISTS evals.planted (
    item_id      VARCHAR(40) NOT NULL,
    kind         VARCHAR(40),
    description  VARCHAR(4000),
    expected     VARCHAR(4000)
);

CREATE TABLE IF NOT EXISTS evals.runs (
    eval_id       VARCHAR(40) NOT NULL,
    metric_name   VARCHAR(100),
    metric_value  DOUBLE,
    detail_json   VARCHAR(2000000),
    created_at    TIMESTAMP
);
