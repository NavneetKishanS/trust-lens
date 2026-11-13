"""Dev A data slice: db adapter, facts.sql, loader."""
import csv
import json
import re
from pathlib import Path

import pytest

from app import audit, config, factsql, load
from app.clinical import facts
from app.db import ExaDatabase, split_statements
from app.devdata import P1
from app.devdata import load as load_fixture

RESERVED = set((Path(__file__).parent / "exasol_reserved_words.txt").read_text().split())
FACTS_SQL = config.REPO_ROOT / "db" / "facts.sql"


# ---------- db adapter ----------
def test_split_statements_respects_strings_and_comments():
    sql = "-- intro; not a statement\nSELECT 'a;b' AS x; /* c; d */ SELECT 2;\n-- trailing"
    assert split_statements(sql) == ["SELECT 'a;b' AS x", "SELECT 2"]


def test_duckdb_named_and_positional_params(db):
    assert db.query("SELECT :a + :a AS x", {"a": 2, "unused": 1}) == [{"x": 4}]
    assert db.query("SELECT ? AS x, CAST(1.50 AS DECIMAL(5,2)) AS d", ["y"]) == [{"x": "y", "d": 1.5}]
    assert db.query("SELECT CAST(42 AS DECIMAL(18,0)) AS n")[0]["n"] == 42  # never Decimal


def test_exasol_binding_inlines_literals_and_quotes_reserved_names():
    sql = "SELECT r.low, text, 'low; text' AS s, \"date\" FROM ref.lab_ranges r WHERE loinc = ? AND x = ?"
    out = ExaDatabase._rewrite(sql, ["2339-0", "it's"])
    assert out == ("SELECT r.\"LOW\", \"TEXT\", 'low; text' AS s, \"date\" FROM \"REF\".lab_ranges r "
                   "WHERE loinc = '2339-0' AND x = 'it''s'")
    assert ExaDatabase._rewrite("SELECT :p AS v, ref_day.d", {"p": None}) == "SELECT NULL AS v, ref_day.d"


# ---------- facts.sql ----------
def _code_only(sql: str) -> str:
    return re.sub(r'"[^"]*"', "", re.sub(r"'[^']*'", "", re.sub(r"--[^\n]*", "", sql)))


def test_facts_sql_blocks_are_portable(db):
    blocks = db.named_blocks(FACTS_SQL)
    assert set(blocks) == {k.lower() for k in facts.KINDS}
    for name, sql in blocks.items():
        aliases = set(re.findall(r"\bAS\s+([a-z_]\w*)", _code_only(sql)))
        bad = aliases & RESERVED - {"text", "low", "high"}  # auto-quoted by app.db on Exasol
        assert not bad, f"{name}: Exasol reserved alias {bad}"
        assert sql.count("?") == _code_only(sql).count("?"), f"{name}: '?' in a comment or string"


@pytest.fixture()
def fixture_with_ref(db):
    load_fixture(db)
    return db


def test_summary_uses_sql_facts(fixture_with_ref):
    from app.clinical import summary

    s = summary.get_summary(P1, "patient")
    assert s["overall_status"] == "verified"
    glucose = next(f for f in s["facts"] if f["kind"] == "LAB_TREND" and f["data"]["loinc"] == "2339-0")
    assert glucose["data"]["latest"] == {"value": 91, "date": "2025-10-02", "flag": "NORMAL"}


# ---------- loader ----------
SYNTHEA = {
    "patients": (["Id", "BIRTHDATE", "DEATHDATE", "SSN", "DRIVERS", "PASSPORT", "FIRST", "LAST", "RACE", "ETHNICITY",
                  "GENDER", "BIRTHPLACE", "ADDRESS", "STATE", "ZIP", "LAT", "LON", "INCOME"],
                 [["p2", "1980-02-01", "", "999-11-2222", "S1", "X1", "Bo1", "Lee2", "white", "nonhispanic", "M",
                   "Boston", "1 Main St", "Massachusetts", "02110", "42.1", "-71.0", "50000"],
                  ["p1", "1970-01-01", "", "999-33-4444", "S2", "X2", "Ann3", "Kim4", "asian", "nonhispanic", "F",
                   "Salem", "2 Side St", "Massachusetts", "01970", "42.5", "-70.9", "60000"]]),
    "encounters": (["Id", "START", "STOP", "PATIENT", "ORGANIZATION", "PROVIDER", "PAYER", "ENCOUNTERCLASS", "CODE",
                    "DESCRIPTION", "REASONCODE", "REASONDESCRIPTION"],
                   [["e1", "2025-03-11T09:00:00Z", "2025-03-11T09:30:00Z", "p1", "o1", "d1", "x", "ambulatory",
                     "185349003", "Check up", "", ""]]),
    "conditions": (["START", "STOP", "PATIENT", "ENCOUNTER", "SYSTEM", "CODE", "DESCRIPTION"],
                   [["2025-03-11", "", "p1", "e1", "SNOMED-CT", "59621000", "Essential hypertension (disorder)"]]),
    "observations": (["DATE", "PATIENT", "ENCOUNTER", "CATEGORY", "CODE", "DESCRIPTION", "VALUE", "UNITS", "TYPE"],
                     [["2025-03-11T09:10:00Z", "p1", "e1", "laboratory", "2339-0", "Glucose", "142.4", "mg/dL", "numeric"],
                      ["2025-03-11T09:10:00Z", "p1", "e1", "survey", "72166-2", "Tobacco", "Never smoked", "", "text"]]),
    "medications": (["START", "STOP", "PATIENT", "PAYER", "ENCOUNTER", "CODE", "DESCRIPTION", "REASONCODE",
                     "REASONDESCRIPTION"], []),
    "immunizations": (["DATE", "PATIENT", "ENCOUNTER", "CODE", "DESCRIPTION", "BASE_COST"],
                      [["2024-10-01T10:00:00Z", "p1", "e1", "207", "COVID-19 mRNA", "100"],
                       ["2024-10-01T10:00:00Z", "p1", "e1", "208", "COVID-19 mRNA", "100"]]),
    "careplans": (["Id", "START", "STOP", "PATIENT", "ENCOUNTER", "CODE", "DESCRIPTION", "REASONCODE",
                   "REASONDESCRIPTION"], []),
    "allergies": (["START", "STOP", "PATIENT", "ENCOUNTER", "CODE", "SYSTEM", "DESCRIPTION", "TYPE", "CATEGORY"], []),
    "providers": (["Id", "ORGANIZATION", "NAME", "ADDRESS"], [["d1", "o1", "Dr. Weber", "3 Clinic Rd"]]),
    "organizations": (["Id", "NAME", "ADDRESS"], [["o1", "Praxis Erlangen", "4 Clinic Rd"]]),
}


@pytest.fixture()
def tiny_csv(tmp_path):
    for name, (header, rows) in SYNTHEA.items():
        with open(tmp_path / f"{name}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(rows)
    return tmp_path


def test_loader_end_to_end(db, tiny_csv, monkeypatch):
    monkeypatch.setenv("ANON_SALT", "test-salt")
    assert load.main(["--reset", "--csv-dir", str(tiny_csv)]) == 0

    pats = db.query("SELECT * FROM curated.patients ORDER BY row_id")
    assert [(p["row_id"], p["patient_id"], p["display_name"], p["source_line"]) for p in pats] == [
        ("PAT-0000001", "p1", "Ann3 Kim4", 3), ("PAT-0000002", "p2", "Bo1 Lee2", 2)]
    blob = json.dumps(db.query("SELECT * FROM curated.patients"), default=str)
    for secret in ("999-11-2222", "1 Main St", "02110", "42.1", "50000", "Boston"):
        assert secret not in blob

    obs = db.query("SELECT row_id, obs_date, value_text, value_num, origin FROM curated.observations ORDER BY row_id")
    assert [(o["row_id"], o["value_num"]) for o in obs] == [("OBS-0000001", 142.4), ("OBS-0000002", None)]
    assert str(obs[0]["obs_date"]) == "2025-03-11" and obs[0]["origin"] == "synthea"
    enc = db.query("SELECT start_ts, provider_name, organization_name FROM curated.encounters")[0]
    assert str(enc["start_ts"]) == "2025-03-11 09:00:00" and enc["provider_name"] == "Dr. Weber"
    assert db.query("SELECT code_system FROM curated.conditions")[0]["code_system"] == "SNOMED"

    pseudo = db.query("SELECT pseudo_id FROM curated.pseudo_ids WHERE patient_id = 'p1'")[0]["pseudo_id"]
    assert pseudo == load.pseudo_id("p1", "test-salt") and re.fullmatch(r"ANON-[0-9a-f]{12}", pseudo)

    concepts = {r["concept_id"]: r for r in db.query("SELECT * FROM ref.concepts")}
    assert "spikevax" in concepts["CVX:207"]["synonyms"].lower()
    assert "high blood pressure" in concepts["SNOMED:59621000"]["synonyms"]
    assert "FREE:myocarditis" in concepts
    assert [r["loinc"] for r in db.query("SELECT loinc FROM ref.lab_ranges")] == ["2339-0"]  # only codes in data

    events = audit.list_events()
    assert events[0]["action_type"] == "data.loaded" and events[0]["payload"]["tables"]["curated.patients"] == 2
    assert audit.verify()["valid"]
    edges = db.query("SELECT source_id FROM gov.lineage_edges WHERE derived_id = 'curated.encounters' ORDER BY 1")
    assert [e["source_id"] for e in edges] == ["file:encounters.csv", "file:organizations.csv", "file:providers.csv"]

    # reload without reset: same row IDs, no duplicate lineage, chain still valid
    assert load.main(["--csv-dir", str(tiny_csv)]) == 0
    assert [p["row_id"] for p in db.query("SELECT row_id FROM curated.patients ORDER BY row_id")] == \
        ["PAT-0000001", "PAT-0000002"]
    assert len(db.query("SELECT 1 AS x FROM gov.lineage_edges WHERE derived_id = 'curated.encounters'")) == 3
    assert audit.verify() == {"valid": True, "length": 2, "broken_at": None}


def test_ref_vocab_is_consistent():
    """Every known effect maps to a vocab term; no synonym belongs to two terms."""
    vocab = list(csv.DictReader(open(config.REPO_ROOT / "db/ref/symptom_vocab.csv", encoding="utf-8")))
    terms = {r["term"] for r in vocab}
    owners = {}
    for r in vocab:
        for s in [x.strip().lower() for x in r["synonyms"].split(";") if x.strip()]:
            assert owners.setdefault(s, r["term"]) == r["term"], s
    effects = list(csv.DictReader(open(config.REPO_ROOT / "db/ref/known_effects.csv", encoding="utf-8")))
    assert {e["effect_term"] for e in effects} <= terms
    assert all(e["source_url"].startswith("https://www.ema.europa.eu/") for e in effects)


# ---------- pool views (A4) ----------
@pytest.fixture()
def pool_db(db, monkeypatch):
    monkeypatch.setenv("ANON_SALT", "test-salt")
    load_fixture(db)
    load.load_pseudo_ids(db)
    load.load_age_bands(db)
    assert load.create_pool_views(db)
    return db


def test_pool_has_no_identifiers(pool_db):
    db = pool_db
    ids = {r["patient_id"] for r in db.query("SELECT patient_id FROM curated.patients")}
    names = {r["display_name"] for r in db.query("SELECT display_name FROM curated.patients")}
    for view in ["patients", "conditions", "observations", "medications", "immunizations", "symptom_reports",
                 "rare_cases"]:
        rows = db.query(f"SELECT * FROM pool.{view}")
        blob = json.dumps(rows, default=str)
        assert not any(i in blob for i in ids | names), view
        assert not re.search(r"\d{4}-\d{2}-\d{2}", blob), f"exact date in pool.{view}"
        assert not re.search(r"\b(OBS|ENC|CON|MED|IMM|CPL|ALG|PAT)-\d{7}\b", blob), f"row id in pool.{view}"
    pats = db.query("SELECT pseudo_id, age_band FROM pool.patients ORDER BY pseudo_id")
    assert all(re.fullmatch(r"ANON-[0-9a-f]{12}", p["pseudo_id"]) for p in pats)
    assert db.query("SELECT age_band_at_dose, imm_month FROM pool.immunizations WHERE concept_code = '207'") == [
        {"age_band_at_dose": "50-59", "imm_month": "2026-10"}]


def test_symptom_loop_reaches_pool_views(pool_db):
    from datetime import date

    from app.clinical import review, symptoms
    from app.research import pool

    r = symptoms.submit_report(P1, "Since my booster I'm tired, have a headache and blurred vision.", date(2026, 10, 30))
    bv = next(s for s in r["symptoms"] if s["term"] == "blurred vision")
    reports = pool_db.query("SELECT term, classification, exposure_code, days_since_exposure, report_month "
                            "FROM pool.symptom_reports ORDER BY term")
    assert [x["term"] for x in reports] == ["fatigue", "headache"]  # pending NEW is not in the pool
    assert reports[0]["exposure_code"] == "207" and reports[0]["days_since_exposure"] == 2
    assert pool.rare_cases()["items"] == []

    review.decide(bv["symptom_id"], "approve", "Dr. Weber", "keep for research")
    assert [x["term"] for x in pool_db.query("SELECT term FROM pool.symptom_reports ORDER BY term")] == \
        ["blurred vision", "fatigue", "headache"]
    assert pool.rare_cases() == {"k": 5, "items": [{
        "term": "blurred vision", "exposure_label": "Moderna (CVX 207)", "age_band": "50-59", "sex": "F",
        "n_reports": "<5", "first_month": "2026-10"}]}


# ---------- seed_signal (A5) ----------
def _seed_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("seed_signal", config.REPO_ROOT / "data" / "seed_signal.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_seed_phrases_map_to_the_vocabulary():
    seed = _seed_module()
    vocab = {r["term"]: {s.strip().lower() for s in r["synonyms"].split(";")}
             for r in csv.DictReader(open(config.REPO_ROOT / "db/ref/symptom_vocab.csv", encoding="utf-8"))}
    for term, phrases in seed.PHRASES.items():
        assert term in vocab, term
        assert all(p.lower() in vocab[term] for p in phrases), term
    assert set(seed.EXPECTED_WEIGHTS) <= set(seed.PHRASES)
    assert len(seed.UNSAFE_QUESTIONS) == 5 and seed._band(95) == "90+" and seed._band(47) == "40-49"
    assert "NEW" not in [t for t, _ in seed.PL3_NEW]


# ---------- exposure_outcome_rate (A6) ----------
def test_exposure_outcome_rate_reads_pool_only_and_counts(pool_db):
    sql = pool_db.named_blocks("db/pool_queries.sql")["exposure_outcome_rate"]
    assert set(re.findall(r"\b([a-z_]\w*)\.[a-z_]", _code_only(sql))) <= {"pool", "a", "c", "e", "o", "p", "pr", "x"}
    assert "concept_code = :exposure_code" in sql  # research/sanity.py rewrites this for vaccine classes
    # fixture: P1 (F, 58) got Moderna 2026-10; P2 has hypertension since 2019 (prevalent, excluded)
    row = pool_db.query(sql, {"exposure_code": "207", "outcome_code": "59621000", "window_days": 90})[0]
    assert row == {"n_exposed": 1, "n_outcome_exposed": 0, "n_unexposed": 1, "n_outcome_unexposed": 0}
    none = pool_db.query(sql, {"exposure_code": "999", "outcome_code": "59621000", "window_days": 90})[0]
    assert none == {"n_exposed": 0, "n_outcome_exposed": 0, "n_unexposed": 0, "n_outcome_unexposed": 0}
