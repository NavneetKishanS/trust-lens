"""Patient list for the clinical views (curated data, display names are synthetic)."""
from __future__ import annotations

from ..db import DB, get_db
from .facts import COVID_VACCINE_CODES, as_date, day


def list_patients(limit: int = 20, vaccinated: bool | None = None, db: DB | None = None) -> list[dict]:
    db = db or get_db()
    codes = ", ".join(f"'{c}'" for c in COVID_VACCINE_CODES)
    where = ""
    if vaccinated is True:
        where = f"WHERE p.patient_id IN (SELECT patient_id FROM curated.immunizations WHERE concept_code IN ({codes}))"
    elif vaccinated is False:
        where = f"WHERE p.patient_id NOT IN (SELECT patient_id FROM curated.immunizations WHERE concept_code IN ({codes}))"
    rows = db.query(
        "SELECT p.patient_id, p.display_name, p.birth_date, p.sex, MAX(e.start_ts) AS last_encounter "
        "FROM curated.patients p LEFT JOIN curated.encounters e ON e.patient_id = p.patient_id "
        f"{where} GROUP BY p.patient_id, p.display_name, p.birth_date, p.sex "
        f"ORDER BY MAX(e.start_ts) DESC, p.patient_id LIMIT {int(limit)}")
    out = []
    for r in rows:
        born, last = as_date(r["birth_date"]), as_date(r["last_encounter"])
        age = None
        if born and last:
            age = last.year - born.year - ((last.month, last.day) < (born.month, born.day))
        out.append({"patient_id": r["patient_id"], "display_name": r["display_name"], "age": age, "sex": r["sex"],
                    "last_encounter": day(r["last_encounter"])})
    return out
