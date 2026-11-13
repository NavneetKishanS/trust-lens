"""Tiny Synthea-shaped dev fixture so the clinical engine runs before Dev A's Synthea load lands.

    .venv/bin/python -m app.devdata          (from backend/, or with --app-dir semantics: cd backend first)

Creates the schema (db/schema.sql via Dev A's loader), inserts 3 synthetic patients into curated.*, every row
labelled origin='dev_fixture', and loads the ref tables from db/ref/*.csv. Refuses to touch a database whose
curated.patients already has rows unless --force.
"""
from __future__ import annotations

import argparse

from .db import DB, get_db

TABLES = ["curated.patients", "curated.encounters", "curated.conditions", "curated.observations",
          "curated.medications", "curated.immunizations", "curated.careplans", "curated.allergies"]

P1, P2, P3 = ("dev-0001-anna", "dev-0002-bernd", "dev-0003-chiara")
MODERNA = "SARS-COV-2 (COVID-19) vaccine, mRNA, spike protein, LNP, preservative free, 100 mcg/0.5mL dose"


def rows() -> dict[str, list[tuple]]:
    return {
        "curated.patients": [
            ("PAT-0000001", P1, "Anna Synthetic", "1968-04-12", None, "F", "white", "nonhispanic", "Bavaria"),
            ("PAT-0000002", P2, "Bernd Synthetic", "1955-09-30", None, "M", "white", "nonhispanic", "Bavaria"),
            ("PAT-0000003", P3, "Chiara Synthetic", "1990-01-05", None, "F", "white", "nonhispanic", "Bavaria"),
        ],
        "curated.encounters": [
            ("ENC-0000001", "e1", P1, "2025-03-11 09:00:00", "2025-03-11 09:30:00", "ambulatory", "185349003",
             "Encounter for check up", None, None, "Dr. Lena Weber", "Praxis Erlangen"),
            ("ENC-0000002", "e2", P1, "2025-10-02 10:00:00", "2025-10-02 10:20:00", "ambulatory", "185349003",
             "Encounter for check up", None, None, "Dr. Lena Weber", "Praxis Erlangen"),
            ("ENC-0000003", "e3", P1, "2026-10-28 08:30:00", "2026-10-28 08:45:00", "ambulatory", "33879002",
             "Administration of vaccine to produce active immunity (procedure)", None, None, "Dr. Lena Weber", "Praxis Erlangen"),
            ("ENC-0000004", "e4", P2, "2026-02-03 11:00:00", "2026-02-03 11:40:00", "ambulatory", "390906007",
             "Follow-up encounter", "59621000", "Essential hypertension (disorder)", "Dr. Jonas Keller", "MVZ Nürnberg"),
            ("ENC-0000005", "e5", P3, "2026-06-15 14:00:00", "2026-06-15 14:15:00", "ambulatory", "185349003",
             "Encounter for check up", None, None, "Dr. Lena Weber", "Praxis Erlangen"),
        ],
        "curated.conditions": [
            ("CON-0000001", P1, "e1", "2025-03-11", None, "SNOMED", "15777000", "Prediabetes (finding)"),
            ("CON-0000002", P2, "e4", "2019-05-20", None, "SNOMED", "59621000", "Essential hypertension (disorder)"),
        ],
        "curated.observations": [
            ("OBS-0000001", P1, "e1", "2025-03-11", "laboratory", "2339-0", "Glucose", "142", 142.0, "mg/dL", "numeric"),
            ("OBS-0000002", P1, "e2", "2025-10-02", "laboratory", "2339-0", "Glucose", "91", 91.0, "mg/dL", "numeric"),
            ("OBS-0000003", P1, "e1", "2025-03-11", "laboratory", "4548-4", "Hemoglobin A1c/Hemoglobin.total in Blood", "6.1", 6.1, "%", "numeric"),
            ("OBS-0000004", P1, "e2", "2025-10-02", "laboratory", "4548-4", "Hemoglobin A1c/Hemoglobin.total in Blood", "5.5", 5.5, "%", "numeric"),
            ("OBS-0000005", P1, "e2", "2025-10-02", "vital-signs", "8480-6", "Systolic Blood Pressure", "118", 118.0, "mm[Hg]", "numeric"),
            ("OBS-0000006", P2, "e4", "2026-02-03", "vital-signs", "8480-6", "Systolic Blood Pressure", "148", 148.0, "mm[Hg]", "numeric"),
            ("OBS-0000007", P2, "e4", "2026-02-03", "laboratory", "2093-3", "Total Cholesterol", "231", 231.0, "mg/dL", "numeric"),
            ("OBS-0000008", P3, "e5", "2026-06-15", "laboratory", "718-7", "Hemoglobin [Mass/volume] in Blood", "11.2", 11.2, "g/dL", "numeric"),
        ],
        "curated.medications": [
            ("MED-0000001", P2, "e4", "2019-05-20 11:00:00", None, "314076", "lisinopril 10 MG Oral Tablet", "59621000",
             "Essential hypertension (disorder)"),
            ("MED-0000002", P1, "e1", "2025-03-11 09:20:00", "2025-09-30 00:00:00", "860975",
             "24 HR Metformin hydrochloride 500 MG Extended Release Oral Tablet", "15777000", "Prediabetes (finding)"),
        ],
        "curated.immunizations": [
            ("IMM-0000001", P1, "e3", "2026-10-28", "207", MODERNA),
            ("IMM-0000002", P2, "e4", "2026-02-03", "140", "Influenza, seasonal, injectable, preservative free"),
        ],
        "curated.careplans": [
            ("CPL-0000001", "cp1", P1, "e1", "2025-03-11", None, "698360004", "Diabetes self management plan",
             "15777000", "Prediabetes (finding)"),
            ("CPL-0000002", "cp2", P2, "e4", "2019-05-20", None, "443402002", "Lifestyle education regarding hypertension",
             "59621000", "Essential hypertension (disorder)"),
        ],
        "curated.allergies": [
            ("ALG-0000001", P3, "2015-01-01", None, "300916003", "Latex allergy", "environment"),
        ],
    }


def load(db: DB | None = None, force: bool = False) -> bool:
    """Create the schema (Dev A's schema.sql + Dev B's tables), insert the fixture, load the ref CSVs."""
    from . import load as loader  # Dev A's loader: schema + ref tables

    db = db or get_db()
    loader.create_schema(db, reset=False)
    if db.query("SELECT COUNT(*) AS n FROM curated.patients")[0]["n"] and not force:
        return False
    for table in TABLES:
        db.execute(f"DELETE FROM {table}")
    for table, data in rows().items():
        for line, row in enumerate(data, start=1):
            values = [*row, "dev_fixture.py", line, "dev_fixture"]
            db.execute(f"INSERT INTO {table} VALUES ({', '.join('?' for _ in values)})", values)
    loader.load_lab_ranges(db)
    loader.load_symptom_vocab(db)
    loader.load_known_effects(db)
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="replace existing curated tables")
    args = parser.parse_args()
    print("loaded dev fixture" if load(force=args.force) else "curated.patients has rows; use --force to replace")
