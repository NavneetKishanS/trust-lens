"""DEV STAND-IN for Dev A's anonymised pool (db/pool_views.sql). Not used once the real views exist.

Creates pool.* as small *tables* with the exact shared §6 columns, filled with deterministic synthetic data
(seed 42) including a planted signal like PL2 (extra hypertension onsets within 3 months after CVX 207 in
patients ≥ 40) and a few approved NEW symptoms. Lets the research engine and UI run before Dev A's pool lands.

    python -m app.research.devpool          # create if pool.patients doesn't exist yet
    python -m app.research.devpool --drop   # remove the stand-in (do this before Dev A's load --reset)

Never point this at Exasol: it refuses unless the database is the local DuckDB fallback.
"""
from __future__ import annotations

import argparse
import hashlib
import random

from app.research import deps

TABLES = ["rare_cases", "symptom_reports", "immunizations", "medications", "observations", "conditions", "patients"]
DDL = """
CREATE SCHEMA IF NOT EXISTS pool;
CREATE TABLE pool.patients (pseudo_id VARCHAR, age_band VARCHAR, sex VARCHAR, race VARCHAR, ethnicity VARCHAR);
CREATE TABLE pool.conditions (pseudo_id VARCHAR, concept_code VARCHAR, description VARCHAR, onset_month VARCHAR,
  age_band_at_onset VARCHAR);
CREATE TABLE pool.observations (pseudo_id VARCHAR, concept_code VARCHAR, description VARCHAR, value_num DOUBLE,
  units VARCHAR, obs_month VARCHAR);
CREATE TABLE pool.medications (pseudo_id VARCHAR, concept_code VARCHAR, description VARCHAR, start_month VARCHAR,
  stop_month VARCHAR);
CREATE TABLE pool.immunizations (pseudo_id VARCHAR, concept_code VARCHAR, description VARCHAR, imm_month VARCHAR,
  age_band_at_dose VARCHAR);
CREATE TABLE pool.symptom_reports (pseudo_id VARCHAR, term VARCHAR, classification VARCHAR, exposure_code VARCHAR,
  exposure_label VARCHAR, days_since_exposure INTEGER, report_month VARCHAR);
CREATE VIEW pool.rare_cases AS
  SELECT s.term, s.exposure_label, p.age_band, p.sex, COUNT(*) AS n_reports, MIN(s.report_month) AS first_month
  FROM pool.symptom_reports s JOIN pool.patients p ON p.pseudo_id = s.pseudo_id
  WHERE s.classification = 'NEW'
  GROUP BY s.term, s.exposure_label, p.age_band, p.sex;
"""

MODERNA = ("207", "SARS-COV-2 (COVID-19) vaccine, mRNA, spike protein, LNP, preservative free, 100 mcg/0.5mL dose")
PFIZER = ("208", "SARS-COV-2 (COVID-19) vaccine, mRNA, spike protein, LNP, preservative free, 30 mcg/0.3mL dose")
FLU = ("140", "Influenza, seasonal, injectable, preservative free")
HYPERTENSION = ("59621000", "Essential hypertension (disorder)")
T2DM = ("44054006", "Diabetes mellitus type 2 (disorder)")
PREDIABETES = ("714628002", "Prediabetes (finding)")
METFORMIN = ("860975", "24 HR Metformin hydrochloride 500 MG Extended Release Oral Tablet")
HBA1C = ("4548-4", "Hemoglobin A1c/Hemoglobin.total in Blood")
EXPECTED = ["fatigue", "headache", "injection site pain", "muscle pain", "chills", "fever", "nausea"]
IN_RECORD = ["joint pain", "dizziness"]
RARE = [("blurred vision", 3), ("tinnitus", 2)]


def band(age: int) -> str:
    lo = min(age // 10 * 10, 90)
    return f"{lo}-{lo + 9}"


def month(idx: int) -> str:
    y, m = divmod(idx - 1, 12)
    return f"{y:04d}-{m + 1:02d}"


def midx(year: int, mon: int) -> int:
    return year * 12 + mon


def generate(n: int = 1000, seed: int = 42) -> dict[str, list[dict]]:
    rng = random.Random(seed)
    out = {t: [] for t in TABLES if t != "rare_cases"}
    ref_year = 2026
    for i in range(n):
        pid = "ANON-" + hashlib.sha256(f"dev-pool|{i}".encode()).hexdigest()[:12]
        age = rng.choice([rng.randint(1, 17), rng.randint(18, 39), rng.randint(40, 64), rng.randint(65, 92)]) \
            if rng.random() < 0.9 else rng.randint(18, 92)
        sex = rng.choice(["F", "M"])
        out["patients"].append(dict(pseudo_id=pid, age_band=band(age), sex=sex,
                                    race=rng.choice(["white", "white", "black", "asian", "other"]),
                                    ethnicity=rng.choice(["nonhispanic", "nonhispanic", "hispanic"])))
        age_at = lambda idx: age - (midx(ref_year, 11) - idx) // 12  # noqa: E731

        dose_idx = None
        if age >= 18 and rng.random() < 0.85:
            vac = MODERNA if rng.random() < 0.65 else PFIZER
            dose_idx = midx(2021, 1) + rng.randint(0, 14)
            for k in range(rng.choice([1, 2, 2, 3])):
                d = dose_idx + k * rng.choice([1, 2, 6])
                out["immunizations"].append(dict(pseudo_id=pid, concept_code=vac[0], description=vac[1],
                                                 imm_month=month(d), age_band_at_dose=band(age_at(d))))
            dose_code = vac[0]
        else:
            dose_code = None
        if rng.random() < 0.6:
            d = midx(rng.randint(2019, 2025), 10)
            out["immunizations"].append(dict(pseudo_id=pid, concept_code=FLU[0], description=FLU[1],
                                             imm_month=month(d), age_band_at_dose=band(age_at(d))))

        # hypertension: background onsets spread over 2010–2025, plus the planted PL2-style signal
        onset = None
        if age >= 30 and rng.random() < 0.28:
            onset = midx(rng.randint(2010, 2025), rng.randint(1, 12))
        if dose_code == "207" and age_at(dose_idx) >= 40 and rng.random() < 0.09:
            onset = dose_idx + rng.randint(0, 3)  # planted: within ~90 days after the first Moderna dose
        elif age >= 18 and rng.random() < 0.15:
            onset = midx(2021, 1) + rng.randint(0, 14)  # background: ~4% per 3-month window in 2021-22
        if onset:
            out["conditions"].append(dict(pseudo_id=pid, concept_code=HYPERTENSION[0], description=HYPERTENSION[1],
                                          onset_month=month(onset), age_band_at_onset=band(age_at(onset))))

        if age >= 30 and rng.random() < 0.18:
            on = midx(rng.randint(2008, 2024), rng.randint(1, 12))
            out["conditions"].append(dict(pseudo_id=pid, concept_code=T2DM[0], description=T2DM[1],
                                          onset_month=month(on), age_band_at_onset=band(age_at(on))))
            out["medications"].append(dict(pseudo_id=pid, concept_code=METFORMIN[0], description=METFORMIN[1],
                                           start_month=month(on + 1), stop_month=None))
            base = rng.uniform(6.6, 9.2)
        elif age >= 30 and rng.random() < 0.15:
            on = midx(rng.randint(2012, 2024), rng.randint(1, 12))
            out["conditions"].append(dict(pseudo_id=pid, concept_code=PREDIABETES[0], description=PREDIABETES[1],
                                          onset_month=month(on), age_band_at_onset=band(age_at(on))))
            base = rng.uniform(5.7, 6.4)
        else:
            base = rng.uniform(4.6, 5.6)
        if age >= 18 and rng.random() < 0.7:
            for k in range(rng.randint(1, 4)):
                out["observations"].append(dict(pseudo_id=pid, concept_code=HBA1C[0], description=HBA1C[1],
                                                value_num=round(base + rng.uniform(-0.4, 0.4), 1), units="%",
                                                obs_month=month(midx(2022 + k, rng.randint(1, 12)))))

        if dose_code and rng.random() < 0.35:
            label = "Moderna (CVX 207)" if dose_code == "207" else "Pfizer-BioNTech (CVX 208)"
            for term in rng.sample(EXPECTED, rng.randint(1, 3)):
                days = rng.randint(0, 10)
                out["symptom_reports"].append(dict(pseudo_id=pid, term=term, classification="EXPECTED",
                                                   exposure_code=dose_code, exposure_label=label,
                                                   days_since_exposure=days, report_month=month(dose_idx)))
            if rng.random() < 0.1:
                out["symptom_reports"].append(dict(pseudo_id=pid, term=rng.choice(IN_RECORD),
                                                   classification="IN_RECORD", exposure_code=dose_code,
                                                   exposure_label=label, days_since_exposure=rng.randint(0, 14),
                                                   report_month=month(dose_idx)))
    # a handful of clinician-approved NEW symptoms (validated rare cases)
    vaccinated = [r for r in out["immunizations"] if r["concept_code"] == "207"]
    for term, count in RARE:
        for r in rng.sample(vaccinated, count):
            out["symptom_reports"].append(dict(pseudo_id=r["pseudo_id"], term=term, classification="NEW",
                                               exposure_code="207", exposure_label="Moderna (CVX 207)",
                                               days_since_exposure=rng.randint(1, 20), report_month=r["imm_month"]))
    return out


def drop(db) -> None:
    db.execute("CREATE SCHEMA IF NOT EXISTS pool")
    db.execute("DROP VIEW IF EXISTS pool.rare_cases")
    for t in TABLES[1:]:
        db.execute(f"DROP TABLE IF EXISTS pool.{t}")


def create(db, force: bool = False, n: int = 1000) -> dict:
    if getattr(db, "dialect", None) != "duckdb" or not isinstance(db, deps.FallbackDuckDB):
        raise RuntimeError("devpool only runs against the local DuckDB fallback")
    if deps.table_exists(db, "pool.patients") and not force:
        return dict(created=False, reason="pool.patients already exists")
    drop(db)
    db.execute(DDL)
    data = generate(n)
    for table, rows in data.items():
        db.insert_rows(f"pool.{table}", rows)
    return dict(created=True, **{t: len(r) for t, r in data.items()})


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--drop", action="store_true")
    ap.add_argument("--force", action="store_true", help="recreate even if pool.patients exists")
    a = ap.parse_args()
    db = deps.get_db()
    if a.drop:
        drop(db)
        print("dropped dev pool")
    else:
        print(create(db, force=a.force))


if __name__ == "__main__":
    main()
