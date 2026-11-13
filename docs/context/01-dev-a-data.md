# Dev A — Data, Exasol, Validation SQL

> Read `00-shared.md` first. This file covers only your slice.

## 1. Mission

Own everything below the API. That means Exasol on AWS, the synthetic data, the schema, the curated layer,
the **validation checks** (the heart of the trust engine), plus the lineage and audit tables.
Your SQL is what the jury will inspect when they ask "why should I trust this verdict?" Keep it readable.

## 2. You deliver (to Dev B)

| Deliverable | By | Notes |
|---|---|---|
| `data/generate.py` → `data/out/*.csv` | H1 | Already drafted; check the defects match §10 of the shared file |
| `db/schema.sql` | H1 | Exactly the tables in shared §6 |
| `backend/app/db.py` (DB access module) | H2 | Interface in §5; DuckDB first, Exasol second |
| `backend/app/load.py` (reset + load CSVs + build curated) | H2 | `python -m app.load --reset` |
| `db/checks.sql` (all 9 checks) | H8 | Format in §4 |
| Exasol Personal live, data loaded | H12 | Switch is just setting `EXASOL_DSN` |
| Exasol AI function probe result | H6 | §6. Tell Dev B what exists |

## 3. Exasol setup (start at H0 — it runs in the background)

1. Install the Exasol Launcher and run `exasol install aws` with team AWS credentials. Docs: https://docs.exasol.com/db/latest/get_started/exasol_personal.htm, repo: https://github.com/exasol/exasol-personal. Expect 10–20 min.
   - Choose an EU region (eu-central-1) for the sovereignty story.
   - If you abort a deployment, terminate the EC2 instances manually in the console.
2. Note the DSN, user and password and put them in `.env` (never commit).
3. Check it works: `pyexasol` connect, `SELECT CURRENT_TIMESTAMP`.
4. Check whether Python UDFs can make outbound HTTPS calls (needed only if we call Claude from inside SQL; that's optional).
5. Optional, for the "ask the DB" moment: the Exasol MCP server (`exasol-mcp-server` on PyPI) and the agent skills
   (https://docs.exasol.com/db/latest/ai/ai_build_agents/mcp-server-as-agent-tool.htm).

**Fallback:** if Exasol isn't up by H12, demo on DuckDB and show Exasol connected for loading only. Say that honestly.

## 4. Validation checks (`db/checks.sql`)

Format: blocks separated by `-- name: <check_name>`. Each block is one SELECT that returns **one row per lab**
with exactly these columns:

```
check_name, lab_id, check_status ('PASS'|'WARN'|'FAIL'), metric (DOUBLE), detail (VARCHAR),
mitigation (VARCHAR or NULL), affected_rows (INTEGER)
```

Checks read from `curated.hba1c` (and `raw.*` where needed). Use portable SQL that runs on both Exasol and DuckDB:
no vendor date functions (use `collected_month` and `curated.months`), use `1.0 * a / b` for ratios,
`||` for concatenation, and `CASE` for status.

| check_name | Logic | WARN | FAIL | Mitigation text |
|---|---|---|---|---|
| `completeness` | NULL `raw_value` share per lab | > 10% | > 30% | Exclude NULLs; report n per lab |
| `test_consistency` | rows whose LOINC is not an HbA1c code | > 0 | > 20% | Exclude non-HbA1c codes |
| `specimen_consistency` | specimen not whole blood | > 0 | > 20% | Exclude non-whole-blood rows |
| `unit_consistency` | lab unit differs from the majority unit | differs | — (convertible) | Convert using the IFCC formula |
| `method_comparability` | more than one `lab_method` in a lab; detail gives the switch date | > 1 method | — | Stratify by method before and after the switch |
| `duplicates` | same patient + lab + date + value appearing more than once | > 0 | — | Deduplicate (keep first `result_id`) |
| `plausibility` | `value_mmol_mol` outside 20–195 | > 0 | > 5% | Exclude implausible values |
| `time_coverage` | months with no data inside the lab's own min–max range | ≥ 2 months | ≥ 6 months | Flag the gap; no interpolation |
| `population_coverage` | share born ≥ 1965 in the lab vs overall | lab < 5% while overall > 30% | — | Report as a limitation; stratify by age |

Every check should also put its own SQL text into `evidence_sql` (Dev B stores it). Target: all 9 seeded
defects detected, with **no** false positives on clean labs. Check this yourself with the eval query in §7.

## 5. `backend/app/db.py` interface (Dev B codes against this)

```python
def get_db() -> "DB": ...           # EXASOL_DSN set → Exasol, else DuckDB file data/trustlens.duckdb
class DB:
    kind: str                       # "exasol" | "duckdb"
    def query(self, sql: str) -> list[dict]: ...   # keys ALWAYS lowercase (Exasol uppercases them)
    def execute(self, sql: str) -> None: ...
    def insert_rows(self, table: str, rows: list[dict]) -> None: ...   # "schema.table"
    def run_script(self, sql_text: str) -> None: ...                    # split on ';'
def lit(v) -> str: ...              # safe SQL literal: None→NULL, str→'..' with '' escaping, numbers as is
```
- DuckDB: one connection guarded by a `threading.Lock` (FastAPI is multi-threaded).
- Exasol: `pyexasol.connect(dsn, user, password, fetch_dict=True)`, using `import_from_iterable` for bulk inserts.
- Reset is `DROP SCHEMA IF EXISTS x CASCADE` for each schema, then `schema.sql`.

## 6. Exasol AI function probe (H6)

Exasol 2026.1 announced in-SQL AI functions (classification, entailment, extraction, translation). An earlier
extension listed `AI_CLASSIFY`, `AI_EXTRACT_ENTITIES`, `AI_ANSWER`, `AI_SENTIMENT`, `AI_TRANSLATE`. **The exact names
aren't confirmed.** List what's actually installed in our instance (system tables / function list) and test one
entailment-style call. Report the result to Dev B. If entailment exists, the verifier agent calls it in SQL. That's
a strong "AI runs next to the data" point for the jury.

## 7. Lineage, audit and eval support

- On load, write one `lineage.edges` row per curated row: `derived_type='curated.hba1c'`, `source_type='raw.lab_results'`,
  `transform='normalize_hba1c'`, `agent='loader'`.
- `audit.events`: you own the table. Dev B owns the append and verify code (shared §9).
- Eval query (keep it in `db/checks.sql` as `-- name: _eval_recall`): join `evals.seeded_defects` to the latest
  `validation.check_results` on `(expected_check, lab_id)` where the status isn't PASS.

## 8. Definition of done

- [ ] `python -m app.load --reset` works on DuckDB **and** Exasol, with identical row counts
- [ ] All 9 checks return one row per lab, all 9 defects detected, no false positives
- [ ] Every curated row has a lineage edge, and every exclusion has a reason
- [ ] Exasol instance in an EU region, credentials shared securely
- [ ] AI function probe result sent to Dev B

## 9. Pitfalls

- Exasol uppercases unquoted identifiers, so normalise keys to lowercase in `db.query`.
- Reserved words: `VALUE`, `UNIT`, `ACTION`, `COMMENT`, `TIMESTAMP` must not be column names.
- Exasol's `CREATE SCHEMA` also switches the current schema, so always fully qualify names.
- Don't change table or column names without updating shared §6.
