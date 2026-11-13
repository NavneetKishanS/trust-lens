"""Dev A data slice: db adapter, facts.sql, loader."""
import csv
import json
import re
from pathlib import Path

import pytest

from app import audit, config, factsql, load
from app.clinical import facts
from app.clinical.ranges import lab_ranges
from app.db import DB, DuckDB, Exasol, split_statements
from app.devdata import P1, P2, P3
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
    out = Exasol._bind(sql, ["2339-0", "it's"])
    assert out == ("SELECT r.\"LOW\", \"TEXT\", 'low; text' AS s, \"date\" FROM \"REF\".lab_ranges r "
                   "WHERE loinc = '2339-0' AND x = 'it''s'")
    assert Exasol._bind("SELECT :p AS v, ref_day.d", {"p": None}) == "SELECT NULL AS v, ref_day.d"


# ---------- facts.sql ----------
def _code_only(sql: str) -> str:
    return re.sub(r'"[^"]*"', "", re.sub(r"'[^']*'", "", re.sub(r"--[^\n]*", "", sql)))


def test_facts_sql_blocks_are_portable():
    blocks = DB.named_blocks(FACTS_SQL)
    assert set(blocks) == {k.lower() for k in facts.KINDS}
    for name, sql in blocks.items():
        aliases = set(re.findall(r"\bAS\s+([a-z_]\w*)", _code_only(sql)))
        bad = aliases & RESERVED - {"text", "low", "high"}  # auto-quoted by app.db on Exasol
        assert not bad, f"{name}: Exasol reserved alias {bad}"
        assert sql.count("?") == _code_only(sql).count("?"), f"{name}: '?' in a comment or string"


@pytest.fixture()
def fixture_with_ref(db):
    load_fixture(db)
    db.run_script(load.SCHEMA_SQL)
    load.load_lab_ranges(db)  # validates LOINC+units against the fixture's observations
    return db


@pytest.mark.parametrize("pid", [P1, P2, P3])
def test_facts_sql_matches_python_builders(fixture_with_ref, pid):
    db = fixture_with_ref
    ref = facts.reference_date(db, pid)
    labs = facts.lab_trends(db, pid, lab_ranges(db))
    encs, plans = facts.encounters(db, pid), facts.careplans(db, pid)
    python = {
        "LAB_TREND": labs, "CONDITION": facts.conditions(db, pid, ref), "MEDICATION": facts.medications(db, pid, ref),
        "IMMUNIZATION": facts.immunizations(db, pid, ref), "ENCOUNTER": encs[:5], "CAREPLAN": plans,
        "ALLERGY": facts.allergies(db, pid), "NEXT_STEP": facts.next_steps(pid, labs, encs, plans),
    }
    sql = {}
    for f in factsql.compute_facts(pid, db):
        sql.setdefault(f["kind"], []).append(f)
    for kind in facts.KINDS:
        want = [(f["data"], f["source_row_ids"]) for f in python[kind]]
        got = [(f["data"], f["source_row_ids"]) for f in sql.get(kind, [])]
        assert got == want, kind


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
