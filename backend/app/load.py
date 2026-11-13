"""Load Synthea CSVs + hand-made reference data into TrustLens (Dev A).

    cd backend
    python -m app.load --reset      # drop every schema, recreate, load (fresh start, audit chain restarts)
    python -m app.load              # reload curated + ref + pool views only; keeps clinical/community/research/gov
    python ../data/seed_signal.py   # then plant PL2/PL3/PL4 (labelled origin='seed_signal')

Target: Exasol if EXASOL_DSN is set, else DuckDB (data/trustlens.duckdb). Nothing else changes.

How it works: each CSV is staged in an in-memory DuckDB (all VARCHAR), transformed with the SQL in
TRANSFORMS below (rename reserved words, drop identifying columns, assign stable row IDs), and streamed
into the target in chunks. Identifying Synthea columns (SSN, DRIVERS, PASSPORT, ADDRESS, LAT, LON, ZIP,
BIRTHPLACE, INCOME, ...) are never selected, so they never reach the target database.

Row IDs: each table is sorted by (patient_id, date, concept_code, source_line) and numbered, e.g.
OBS-0000001. Same CSVs -> same IDs on every reload.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd

from . import audit, lineage
from .db import DB, get_db, repo_path
from .schema import ensure_schema

SCHEMAS = ["raw", "curated", "ref", "clinical", "community", "pool", "research", "gov", "evals"]
SCHEMA_SQL = "db/schema.sql"
POOL_VIEWS_SQL = "db/pool_views.sql"
REF_DIR = "db/ref"
CHUNK_VECTORS = 50  # x 2048 rows per chunk streamed to the target

# Columns we need from each CSV. Anything else (incl. all identifying columns) is ignored.
REQUIRED = {
    "patients": ["Id", "BIRTHDATE", "DEATHDATE", "FIRST", "LAST", "GENDER", "RACE", "ETHNICITY", "STATE"],
    "encounters": ["Id", "START", "STOP", "PATIENT", "ORGANIZATION", "PROVIDER", "ENCOUNTERCLASS", "CODE",
                   "DESCRIPTION", "REASONCODE", "REASONDESCRIPTION"],
    "conditions": ["START", "STOP", "PATIENT", "ENCOUNTER", "CODE", "DESCRIPTION"],
    "observations": ["DATE", "PATIENT", "ENCOUNTER", "CATEGORY", "CODE", "DESCRIPTION", "VALUE", "UNITS", "TYPE"],
    "medications": ["START", "STOP", "PATIENT", "ENCOUNTER", "CODE", "DESCRIPTION", "REASONCODE", "REASONDESCRIPTION"],
    "immunizations": ["DATE", "PATIENT", "ENCOUNTER", "CODE", "DESCRIPTION"],
    "careplans": ["Id", "START", "STOP", "PATIENT", "ENCOUNTER", "CODE", "DESCRIPTION", "REASONCODE",
                  "REASONDESCRIPTION"],
    "allergies": ["START", "STOP", "PATIENT", "CODE", "DESCRIPTION", "CATEGORY"],
    "providers": ["Id", "NAME"],
    "organizations": ["Id", "NAME"],
}

# Staging macros (DuckDB, staging only):
#   ts_(s)  Synthea ISO timestamp '2019-02-17T05:07:38Z' (UTC) -> 'YYYY-MM-DD HH:MM:SS.mmm'
#   d_(s)   date or timestamp -> 'YYYY-MM-DD'
#   rid(p, n) -> 'OBS-0000001'
STAGING_MACROS = [
    "CREATE MACRO ts_(s) AS strftime(CAST(replace(replace(s, 'T', ' '), 'Z', '') AS TIMESTAMP), '%Y-%m-%d %H:%M:%S.%g')",
    "CREATE MACRO d_(s) AS CAST(CAST(substr(s, 1, 10) AS DATE) AS VARCHAR)",
    "CREATE MACRO rid(p, n) AS p || '-' || lpad(CAST(n AS VARCHAR), 7, '0')",
]

# target table -> transform over staged CSVs (stg_<file>, with source_line = CSV line number)
TRANSFORMS = {
    "curated.patients": """
        SELECT rid('PAT', row_number() OVER (ORDER BY Id, source_line)) AS row_id,
               Id AS patient_id,
               trim(coalesce(FIRST, '') || ' ' || coalesce(LAST, '')) AS display_name,
               d_(BIRTHDATE) AS birth_date, d_(DEATHDATE) AS death_date,
               GENDER AS sex, RACE AS race, ETHNICITY AS ethnicity, STATE AS state,
               'patients.csv' AS source_file, source_line, 'synthea' AS origin
        FROM stg_patients""",
    "curated.encounters": """
        SELECT rid('ENC', row_number() OVER (ORDER BY e.PATIENT, e.START, e.CODE, e.source_line)) AS row_id,
               e.Id AS encounter_id, e.PATIENT AS patient_id, ts_(e.START) AS start_ts, ts_(e.STOP) AS stop_ts,
               e.ENCOUNTERCLASS AS encounter_class, e.CODE AS concept_code, e.DESCRIPTION AS description,
               e.REASONCODE AS reason_code, e.REASONDESCRIPTION AS reason_description,
               p.NAME AS provider_name, o.NAME AS organization_name,
               'encounters.csv' AS source_file, e.source_line, 'synthea' AS origin
        FROM stg_encounters e
        LEFT JOIN stg_providers p ON p.Id = e.PROVIDER
        LEFT JOIN stg_organizations o ON o.Id = e.ORGANIZATION""",
    "curated.conditions": """
        SELECT rid('CON', row_number() OVER (ORDER BY PATIENT, START, CODE, source_line)) AS row_id,
               PATIENT AS patient_id, ENCOUNTER AS encounter_id, d_(START) AS start_date, d_(STOP) AS stop_date,
               {code_system} AS code_system, CODE AS concept_code, DESCRIPTION AS description,
               'conditions.csv' AS source_file, source_line, 'synthea' AS origin
        FROM stg_conditions""",
    "curated.observations": """
        SELECT rid('OBS', row_number() OVER (ORDER BY PATIENT, DATE, CODE, source_line)) AS row_id,
               PATIENT AS patient_id, ENCOUNTER AS encounter_id, d_(DATE) AS obs_date, CATEGORY AS category,
               CODE AS concept_code, DESCRIPTION AS description,
               VALUE AS value_text, TRY_CAST(VALUE AS DOUBLE) AS value_num, UNITS AS units, TYPE AS value_type,
               'observations.csv' AS source_file, source_line, 'synthea' AS origin
        FROM stg_observations""",
    "curated.medications": """
        SELECT rid('MED', row_number() OVER (ORDER BY PATIENT, START, CODE, source_line)) AS row_id,
               PATIENT AS patient_id, ENCOUNTER AS encounter_id, ts_(START) AS start_ts, ts_(STOP) AS stop_ts,
               CODE AS concept_code, DESCRIPTION AS description,
               REASONCODE AS reason_code, REASONDESCRIPTION AS reason_description,
               'medications.csv' AS source_file, source_line, 'synthea' AS origin
        FROM stg_medications""",
    "curated.immunizations": """
        SELECT rid('IMM', row_number() OVER (ORDER BY PATIENT, DATE, CODE, source_line)) AS row_id,
               PATIENT AS patient_id, ENCOUNTER AS encounter_id, d_(DATE) AS imm_date,
               CODE AS concept_code, DESCRIPTION AS description,
               'immunizations.csv' AS source_file, source_line, 'synthea' AS origin
        FROM stg_immunizations""",
    "curated.careplans": """
        SELECT rid('CPL', row_number() OVER (ORDER BY PATIENT, START, CODE, source_line)) AS row_id,
               Id AS careplan_id, PATIENT AS patient_id, ENCOUNTER AS encounter_id,
               d_(START) AS start_date, d_(STOP) AS stop_date, CODE AS concept_code, DESCRIPTION AS description,
               REASONCODE AS reason_code, REASONDESCRIPTION AS reason_description,
               'careplans.csv' AS source_file, source_line, 'synthea' AS origin
        FROM stg_careplans""",
    "curated.allergies": """
        SELECT rid('ALG', row_number() OVER (ORDER BY PATIENT, START, CODE, source_line)) AS row_id,
               PATIENT AS patient_id, d_(START) AS start_date, d_(STOP) AS stop_date,
               CODE AS concept_code, DESCRIPTION AS description, CATEGORY AS category,
               'allergies.csv' AS source_file, source_line, 'synthea' AS origin
        FROM stg_allergies""",
}

# Which CSV feeds which curated table (for lineage and the audit payload).
TABLE_FILES = {
    "curated.patients": ["patients.csv"],
    "curated.encounters": ["encounters.csv", "providers.csv", "organizations.csv"],
    "curated.conditions": ["conditions.csv"],
    "curated.observations": ["observations.csv"],
    "curated.medications": ["medications.csv"],
    "curated.immunizations": ["immunizations.csv"],
    "curated.careplans": ["careplans.csv"],
    "curated.allergies": ["allergies.csv"],
}

POOL_VIEW_SOURCES = {
    "pool.patients": ["curated.patients", "curated.pseudo_ids"],
    "pool.conditions": ["curated.conditions", "curated.patients", "curated.pseudo_ids"],
    "pool.observations": ["curated.observations", "curated.pseudo_ids"],
    "pool.medications": ["curated.medications", "curated.pseudo_ids"],
    "pool.immunizations": ["curated.immunizations", "curated.patients", "curated.pseudo_ids"],
    "pool.symptom_reports": ["community.symptoms", "community.reports", "curated.immunizations",
                             "ref.known_effects", "curated.pseudo_ids"],
    "pool.rare_cases": ["community.symptoms", "community.reports", "curated.immunizations",
                        "ref.known_effects", "curated.patients", "curated.pseudo_ids"],
}


# --------------------------------------------------------------------------------------------
# Small shared helpers (also used by data/seed_signal.py)
# --------------------------------------------------------------------------------------------

def log(msg: str) -> None:
    print(msg, flush=True)


def anon_salt() -> str:
    salt = os.getenv("ANON_SALT", "")
    if not salt:
        log("WARNING: ANON_SALT is not set; using an insecure dev default. Set the team's shared value in .env.")
        salt = "trustlens-dev-salt"
    return salt


def pseudo_id(patient_id: str, salt: str) -> str:
    """Shared §5: 'ANON-' + first 12 hex of sha256(ANON_SALT + patient_uuid)."""
    return "ANON-" + hashlib.sha256((salt + patient_id).encode("utf-8")).hexdigest()[:12]


def add_lineage(db: DB, rows: list[tuple[str, str, str, str, str]]) -> None:
    """rows: (derived_id, derived_type, source_id, source_type, transform). Edges from an earlier load with the
    same (derived_id, transform) are replaced, so reloads don't duplicate them."""
    groups: dict[tuple[str, str, str], list[tuple[str, str]]] = {}
    for derived_id, derived_type, source_id, source_type, transform in rows:
        groups.setdefault((derived_id, derived_type, transform), []).append((source_id, source_type))
    for (derived_id, derived_type, transform), sources in groups.items():
        db.execute("DELETE FROM gov.lineage_edges WHERE derived_id = ? AND transform = ?", [derived_id, transform])
        lineage.add(derived_id, derived_type, sources, transform=transform, db=db)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _split_synonyms(s) -> list[str]:
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return []
    return [x.strip() for x in str(s).split(";") if x.strip()]


def _join_synonyms(items: list[str]) -> str:
    seen, out = set(), []
    for x in items:
        k = x.lower()
        if k not in seen:
            seen.add(k)
            out.append(x)
    return "; ".join(out)


def _read_ref_csv(name: str) -> pd.DataFrame:
    df = pd.read_csv(repo_path(REF_DIR) / name, dtype=str, keep_default_na=False)
    return df.apply(lambda col: col.str.strip()).replace({"": None})


# --------------------------------------------------------------------------------------------
# Steps
# --------------------------------------------------------------------------------------------

def create_schema(db: DB, reset: bool) -> None:
    if reset:
        for s in SCHEMAS:
            db.execute(f"DROP SCHEMA IF EXISTS {s} CASCADE")
        log(f"dropped schemas: {', '.join(SCHEMAS)}")
    db.run_script(SCHEMA_SQL)
    ensure_schema(db)  # Dev B's gov + clinical tables


def stage_csvs(csv_dir: Path):
    """Read each CSV into an in-memory DuckDB table stg_<name> (all VARCHAR) + source_line."""
    import duckdb

    stg = duckdb.connect()
    stg.execute("SET preserve_insertion_order = true")
    for m in STAGING_MACROS:
        stg.execute(m)
    files = {}
    for name, cols in REQUIRED.items():
        path = csv_dir / f"{name}.csv"
        if not path.exists():
            raise SystemExit(f"missing {path}. Generate Synthea CSVs first (docs/context/01-dev-a-data.md §4).")
        stg.execute(f"CREATE TABLE raw_{name} AS SELECT * FROM read_csv(?, header = true, all_varchar = true)",
                    [str(path)])
        header = [r[0] for r in stg.execute(f"DESCRIBE raw_{name}").fetchall()]
        missing = [c for c in cols if c not in header]
        if missing:
            raise SystemExit(f"{path.name}: missing columns {missing}. Header is {header}")
        # rowid follows file order (preserve_insertion_order); header is line 1, so data starts at line 2
        stg.execute(f"CREATE TABLE stg_{name} AS SELECT *, CAST(rowid + 2 AS INTEGER) AS source_line FROM raw_{name}")
        stg.execute(f"DROP TABLE raw_{name}")
        n = stg.execute(f"SELECT COUNT(*) FROM stg_{name}").fetchone()[0]
        files[f"{name}.csv"] = {"rows": n, "sha256": _sha256_file(path)}
        if name == "conditions":
            files["_conditions_has_system"] = "SYSTEM" in header
    return stg, files


def load_curated(db: DB, stg, has_system: bool) -> dict[str, int]:
    counts = {}
    for table, sql in TRANSFORMS.items():
        t0 = time.time()
        if table == "curated.conditions":
            code_system = ("CASE WHEN upper(SYSTEM) LIKE 'SNOMED%' THEN 'SNOMED' ELSE upper(SYSTEM) END"
                           if has_system else "'SNOMED'")
            sql = sql.format(code_system=code_system)
        db.execute(f"DELETE FROM {table}")
        res = stg.execute(sql + "\nORDER BY row_id")
        n = 0
        while True:
            df = res.fetch_df_chunk(CHUNK_VECTORS)
            if df is None or len(df) == 0:
                break
            db.insert_df(table, df)
            n += len(df)
        counts[table] = n
        log(f"  {table:<24} {n:>8} rows  {time.time() - t0:5.1f}s")
    return counts


def load_pseudo_ids(db: DB) -> int:
    salt = anon_salt()
    ids = [r["patient_id"] for r in db.query("SELECT patient_id FROM curated.patients ORDER BY patient_id")]
    db.execute("DELETE FROM curated.pseudo_ids")
    rows = [{"patient_id": p, "pseudo_id": pseudo_id(p, salt)} for p in ids]
    if len({r["pseudo_id"] for r in rows}) != len(rows):
        raise SystemExit("pseudo_id collision; pick another ANON_SALT")
    db.insert_rows("curated.pseudo_ids", rows)
    return len(rows)


def load_lab_ranges(db: DB) -> int:
    df = _read_ref_csv("lab_ranges.csv")
    present = {(r["concept_code"], r["units"]) for r in db.query(
        "SELECT DISTINCT concept_code, units FROM curated.observations WHERE value_num IS NOT NULL")}
    keep = []
    for r in df.to_dict("records"):
        if (r["loinc"], r["units"]) in present:
            keep.append(dict(r, low=float(r["low"]), high=float(r["high"])))
        else:
            log(f"  WARNING lab_ranges: LOINC {r['loinc']} with units {r['units']} not in observations; skipped")
    db.execute("DELETE FROM ref.lab_ranges")
    db.insert_rows("ref.lab_ranges", keep)
    return len(keep)


def load_symptom_vocab(db: DB) -> int:
    df = _read_ref_csv("symptom_vocab.csv")
    owner: dict[str, str] = {}
    rows = []
    for r in df.to_dict("records"):
        term = r["term"].lower()
        syns = [s.lower() for s in _split_synonyms(r["synonyms"])]
        if term not in syns:
            syns.insert(0, term)
        for s in syns:
            if s in owner and owner[s] != term:
                raise SystemExit(f"symptom_vocab: synonym '{s}' is used by both '{owner[s]}' and '{term}'")
            owner[s] = term
        rows.append({"term": term, "synonyms": _join_synonyms(syns), "snomed_code": r["snomed_code"]})
    db.execute("DELETE FROM ref.symptom_vocab")
    db.insert_rows("ref.symptom_vocab", rows)
    return len(rows)


def load_known_effects(db: DB) -> int:
    df = _read_ref_csv("known_effects.csv")
    vocab = {r["term"] for r in db.query("SELECT term FROM ref.symptom_vocab")}
    cvx = {r["concept_code"] for r in db.query("SELECT DISTINCT concept_code FROM curated.immunizations")}
    rows = []
    for r in df.to_dict("records"):
        if r["effect_term"] not in vocab:
            raise SystemExit(f"known_effects: '{r['effect_term']}' is not a term in symptom_vocab.csv")
        if r["product_system"] == "CVX" and r["product_code"] not in cvx:
            log(f"  WARNING known_effects: CVX {r['product_code']} not in immunizations; kept anyway")
        rows.append(dict(r, window_days=int(r["window_days"])))
    db.execute("DELETE FROM ref.known_effects")
    db.insert_rows("ref.known_effects", rows)
    return len(rows)


_SEMANTIC_TAGS = (" (disorder)", " (finding)", " (situation)", " (procedure)", " (person)",
                  " (morphologic abnormality)", " (regime/therapy)", " (observable entity)")


def _clean_label(label: str) -> str:
    for tag in _SEMANTIC_TAGS:
        if label.endswith(tag):
            return label[: -len(tag)]
    return label


def load_concepts(db: DB) -> int:
    """One row per distinct code in conditions, medications, immunizations and the lab LOINCs,
    plus hand synonyms (db/ref/concept_synonyms.csv) and FREE: concepts for research topics we
    don't have codes for in the data."""
    found = db.query("""
        SELECT code_system, concept_code, MIN(description) AS label FROM (
            SELECT code_system, concept_code, description FROM curated.conditions
            UNION ALL SELECT 'RXNORM', concept_code, description FROM curated.medications
            UNION ALL SELECT 'CVX', concept_code, description FROM curated.immunizations
            UNION ALL SELECT 'LOINC', loinc, name FROM ref.lab_ranges
        ) c
        WHERE concept_code IS NOT NULL
        GROUP BY code_system, concept_code
    """)
    plain = {r["loinc"]: r["plain_name"] for r in db.query("SELECT loinc, plain_name FROM ref.lab_ranges")}
    concepts: dict[str, dict] = {}
    for r in found:
        cid = f"{r['code_system']}:{r['concept_code']}"
        label = r["label"] or cid
        syns = [_clean_label(label).lower()]
        if r["code_system"] == "LOINC" and plain.get(r["concept_code"]):
            syns.append(plain[r["concept_code"]].lower())
        concepts[cid] = {"concept_id": cid, "code_system": r["code_system"], "concept_code": r["concept_code"],
                         "label": label, "synonyms": syns}

    for r in _read_ref_csv("concept_synonyms.csv").to_dict("records"):
        cid = r["concept_id"]
        system, _, code = cid.partition(":")
        hand = _split_synonyms(r["synonyms"])
        if cid in concepts:
            if r["label"]:
                concepts[cid]["label"] = r["label"]
            concepts[cid]["synonyms"] += hand
        elif system == "FREE":
            concepts[cid] = {"concept_id": cid, "code_system": "FREE", "concept_code": code,
                             "label": r["label"] or code, "synonyms": hand}
        else:
            log(f"  WARNING concept_synonyms: {cid} is not in the data; skipped (never invent codes)")

    rows = [dict(c, synonyms=_join_synonyms(c["synonyms"])) for c in concepts.values()]
    rows.sort(key=lambda c: c["concept_id"])
    db.execute("DELETE FROM ref.concepts")
    db.insert_rows("ref.concepts", rows)
    return len(rows)


def create_pool_views(db: DB) -> bool:
    if not repo_path(POOL_VIEWS_SQL).exists():
        log(f"  {POOL_VIEWS_SQL} not found; pool views skipped")
        return False
    db.run_script(POOL_VIEWS_SQL)
    return True


# --------------------------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.load", description=__doc__.split("\n\n")[0])
    ap.add_argument("--reset", action="store_true", help="drop ALL schemas first (wipes clinical, gov, ...)")
    ap.add_argument("--csv-dir", default=os.getenv("SYNTHEA_CSV_DIR", "data/synthea/csv"))
    args = ap.parse_args(argv)

    t_start = time.time()
    csv_dir = repo_path(args.csv_dir)
    db = get_db()
    log(f"target: {db.dialect}   csv: {csv_dir}")

    create_schema(db, args.reset)

    log("staging CSVs ...")
    stg, files = stage_csvs(csv_dir)
    has_system = files.pop("_conditions_has_system")

    log("loading curated ...")
    counts = load_curated(db, stg, has_system)
    stg.close()
    counts["curated.pseudo_ids"] = load_pseudo_ids(db)

    log("loading ref ...")
    counts["ref.lab_ranges"] = load_lab_ranges(db)
    counts["ref.symptom_vocab"] = load_symptom_vocab(db)
    counts["ref.known_effects"] = load_known_effects(db)
    counts["ref.concepts"] = load_concepts(db)
    for t in ["ref.lab_ranges", "ref.symptom_vocab", "ref.known_effects", "ref.concepts"]:
        log(f"  {t:<24} {counts[t]:>8} rows")

    log("creating pool views ...")
    has_pool = create_pool_views(db)

    lineage = []
    for table, srcs in TABLE_FILES.items():
        lineage += [(table, "table", f"file:{f}", "file", "load:synthea") for f in srcs]
    lineage.append(("curated.pseudo_ids", "table", "curated.patients", "table", "load:pseudonymise"))
    for t, f in [("ref.lab_ranges", "lab_ranges.csv"), ("ref.symptom_vocab", "symptom_vocab.csv"),
                 ("ref.known_effects", "known_effects.csv")]:
        lineage.append((t, "table", f"file:{REF_DIR}/{f}", "file", "load:ref"))
    lineage += [("ref.concepts", "table", s, "table", "load:concepts")
                for s in ["curated.conditions", "curated.medications", "curated.immunizations", "ref.lab_ranges"]]
    lineage.append(("ref.concepts", "table", f"file:{REF_DIR}/concept_synonyms.csv", "file", "load:concepts"))
    for view, srcs in (POOL_VIEW_SOURCES.items() if has_pool else []):
        lineage += [(view, "view", s, "table", "view:pool_views.sql") for s in srcs]
    add_lineage(db, lineage)

    seq = audit.append("loader", "data.loaded", "curated", {
        "dialect": db.dialect, "reset": args.reset, "tables": counts, "files": files,
    }, db=db)
    log(f"audit data.loaded seq={seq}")
    log(f"done in {time.time() - t_start:.1f}s. Next: python ../data/seed_signal.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
