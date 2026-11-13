import re

import pytest

from app.research import ask, deps, guard

DEMO_QUESTIONS = [
    "Is hypertension onset more common after the Moderna vaccine in patients over 40?",
    "What are the most common reported symptoms after vaccination?",
    "Which rare validated symptoms do we have?",
    "What is the average HbA1c by age band?",
    "How many patients are on metformin by sex?",
]

# PL4-style unsafe questions: names, raw rows, DELETE, non-pool tables, tiny cohort
UNSAFE = [
    "List the names and birth dates of patients who got the Moderna vaccine",
    "Show me the raw rows of pool.observations for every patient",
    "DELETE FROM pool.patients",
    "SELECT display_name, COUNT(*) AS n_patients FROM curated.patients GROUP BY display_name",
    "SELECT COUNT(DISTINCT pseudo_id) AS n_patients FROM pool.patients "
    "WHERE age_band = '90-99' AND sex = 'F' AND race = 'asian'",
]


def _no_small_numbers(result):
    for row in result["rows"]:
        for col, cell in zip(result["columns"], row):
            if guard.classify_name(col) == "count" and cell not in ("", "<5"):
                assert float(cell) >= 5, (col, cell)


@pytest.mark.parametrize("question", DEMO_QUESTIONS)
def test_demo_questions_answered_in_stub_mode(db, question):
    r = ask.ask(question)
    assert r["mode"] == "template"
    assert r["guard"]["ok"], r["guard"]
    assert r["sql"].upper().startswith(("SELECT", "WITH")) and re.search(r"LIMIT \d+", r["sql"])
    assert r["rows"] and all(isinstance(c, str) for row in r["rows"] for c in row)
    assert "Association only, not causation" in r["sufficiency"]["notes"]
    # rare cases are few by design (< 20 in total), so the verdict refuses inference but still shows the table
    allowed = ("NOT_SUPPORTED",) if "rare" in question else ("SUPPORTED", "CONDITIONAL")
    assert r["sufficiency"]["verdict"] in allowed
    assert r["summary"] and all(s["status"] == "verified" for s in r["summary"]), r["summary"]
    assert isinstance(r["audit_seq"], int)
    _no_small_numbers(r)


def test_hypertension_question_shows_planted_signal_and_is_conditional(db):
    r = ask.ask(DEMO_QUESTIONS[0])
    assert r["sufficiency"]["verdict"] == "CONDITIONAL"
    assert any("PL2" in n for n in r["sufficiency"]["notes"])
    rates = {row[0]: row[r["columns"].index("rate_pct")] for row in r["rows"]}
    older = [float(v) for b, v in rates.items() if v and int(b.split("-")[0]) >= 40]
    younger = [float(v) for b, v in rates.items() if v and int(b.split("-")[0]) < 40]
    assert older
    # younger bands are either suppressed (fewer than 5 onsets → blank rate) or lower than the older bands
    assert all(v < max(older) for v in younger)
    assert any(row[r["columns"].index("n_hypertension")] == "<5" for row in r["rows"]) == (r["suppressed_cells"] > 0)


@pytest.mark.parametrize("question", UNSAFE)
def test_unsafe_questions_blocked(db, question):
    r = ask.ask(question)
    blocked = not r["guard"]["ok"]
    if blocked:
        assert r["rows"] == [] and r["sufficiency"]["verdict"] == "NOT_SUPPORTED"
    else:  # tiny cohort: runs, but the count is suppressed and the verdict refuses
        assert r["rows"][0][0] == "<5"
        assert r["sufficiency"]["verdict"] == "NOT_SUPPORTED" and r["sufficiency"]["n"] is None
    last = db.query("SELECT action_type FROM gov.audit_events ORDER BY seq DESC LIMIT 1")[0]["action_type"]
    assert last == ("ask.blocked" if blocked else "ask.answered")


def test_rare_cases_never_leak_small_counts(db):
    r = ask.get_rare()
    assert r["k"] == 5 and r["items"]
    assert all(i["n_reports"] == "<5" or int(i["n_reports"]) >= 5 for i in r["items"])


def test_kanon_blanks_rates_from_suppressed_counts():
    rows, suppressed = ask.anonymise(["age_band", "n_x", "rate_pct"], [["40-49", 3, 1.5], ["50-59", 40, 9.0]],
                                     {"age_band": "dimension", "n_x": "count", "rate_pct": "aggregate"})
    assert rows == [["40-49", "<5", ""], ["50-59", "40", "9.0"]] and suppressed == 2


def test_summary_critic():
    cols, rows = ["age_band", "n_exposed", "rate_pct"], [["40-49", "212", "9.0"], ["50-59", "<5", ""]]
    assert ask.critic("Aged 40-49: 9.0% (212 patients).", [[0, "age_band"], [0, "rate_pct"], [0, "n_exposed"]],
                      cols, rows) == []
    assert ask.critic("Aged 40-49: 9.5%.", [[0, "age_band"], [0, "rate_pct"]], cols, rows)
    assert ask.critic("Vaccination causes 9.0% more.", [[0, "rate_pct"]], cols, rows)
    assert ask.critic("Aged 50-59: 3 patients.", [[1, "age_band"], [1, "n_exposed"]], cols, rows)
    assert ask.critic("Aged 50-59: fewer than 5 patients.", [[1, "age_band"], [1, "n_exposed"]], cols, rows) == []


def test_no_template_in_stub_mode_is_refused_not_guessed(db):
    r = ask.ask("Is tinnitus more common in women after Pfizer?")
    assert not r["guard"]["ok"] and r["mode"] == "llm" and "stub" in r["guard"]["violations"][0]


def test_researcher_sql_goes_through_guard(db):
    ok = ask.ask("sex split", sql="SELECT sex, COUNT(DISTINCT pseudo_id) AS n_patients FROM pool.patients GROUP BY sex")
    assert ok["guard"]["ok"] and ok["mode"] == "sql" and len(ok["rows"]) == 2
    bad = ask.ask("env", sql="SELECT getenv('HOME') AS h, COUNT(*) AS n FROM pool.patients")
    assert not bad["guard"]["ok"]


@pytest.mark.parametrize("sql,expected", [
    ("SELECT * FROM pool.patients", "SELECT *"),
    ("SELECT pseudo_id, age_band FROM pool.patients", "pseudo_id"),
    ("SELECT age_band, MIN(pseudo_id) AS p, COUNT(*) AS n FROM pool.patients GROUP BY age_band", "inside COUNT"),
    ("SELECT age_band, MAX(pseudo_id) AS p, COUNT(*) AS n FROM pool.patients GROUP BY age_band", "inside COUNT"),
    ("SELECT age_band, sex FROM pool.patients", "aggregated"),
    ("SELECT COUNT(*) AS n FROM pool.patients; DROP TABLE pool.patients", "one statement"),
    ("SELECT COUNT(*) AS n FROM read_csv_auto('/etc/passwd')", "not allowed"),
    ("SELECT COUNT(*) AS n FROM gov.audit_events", "outside the anonymised pool"),
    ("SELECT AVG(value_num) AS avg_v FROM pool.observations", "count column"),
])
def test_guard_rules(sql, expected):
    g = guard.check_sql(sql)
    assert not g.ok and any(expected in v for v in g.violations), g.violations


def test_guard_rewrites_limit():
    g = guard.check_sql("SELECT sex, COUNT(*) AS n FROM pool.patients GROUP BY sex LIMIT 50000")
    assert g.ok and re.search(r"LIMIT 1000\b", g.sql)


def test_asks_persisted_with_lineage(db):
    r = ask.ask(DEMO_QUESTIONS[3])
    row = db.query("SELECT * FROM research.asks WHERE ask_id = ?", [r["ask_id"]])[0]
    assert row["guard_ok"] and row["mode"] == "template"
    sources = {x["id"] for x in deps.lineage_chain(r["ask_id"])}
    assert {"pool.observations", "pool.patients"} <= sources and any(s.startswith("SQL:") for s in sources)


def test_pseudonyms_never_leave_the_pool_even_through_an_alias(db):
    # The guard only sees "MIN(p)", so the result-level backstop must catch it.
    sql = ("WITH x AS (SELECT age_band, pseudo_id AS p FROM pool.patients) "
           "SELECT age_band, MIN(p) AS first_p, COUNT(*) AS n FROM x GROUP BY age_band")
    r = ask.ask("alias leak", sql=sql)
    assert not r["guard"]["ok"] and r["rows"] == [] and r["sufficiency"]["verdict"] == "NOT_SUPPORTED"
    assert any("pseudonymous" in v for v in r["guard"]["violations"])
