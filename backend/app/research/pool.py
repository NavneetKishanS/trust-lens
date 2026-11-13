"""Rare validated cases for researchers (/pool/rare).

Interim version by Dev B so the M2 exit test works end to end. Dev C owns this slice: once Dev A's pool.rare_cases
view exists it is read directly; until then the same aggregation runs on community.symptoms + curated.patients.
Only approved NEW/UNMAPPED symptoms count. No IDs leave this function, and counts under k are shown as "<5".
"""
from __future__ import annotations

from datetime import date

from ..db import DB, get_db
from ..schema import table_exists

K = 5


def _band(born: date | None, at: date | None) -> str:
    if not born or not at:
        return "unknown"
    age = at.year - born.year - ((at.month, at.day) < (born.month, born.day))
    low = (age // 10) * 10
    return f"{low}-{low + 9}"


def _count(n: int) -> str:
    return f"<{K}" if n < K else str(n)


def rare_cases(db: DB | None = None) -> dict:
    db = db or get_db()
    if table_exists(db, "pool.rare_cases"):
        rows = db.query("SELECT term, exposure_label, age_band, sex, n_reports, first_month FROM pool.rare_cases")
        items = [{**r, "n_reports": _count(int(r["n_reports"]))} for r in rows]
        return {"k": K, "items": items}
    if not table_exists(db, "community.symptoms") or not table_exists(db, "curated.patients"):
        return {"k": K, "items": []}

    from ..clinical.facts import as_date

    rows = db.query(
        "SELECT s.term, s.exposure_label, s.onset_date, p.birth_date, p.sex FROM community.symptoms s "
        "JOIN curated.patients p ON p.patient_id = s.patient_id "
        "WHERE s.classification IN ('NEW', 'UNMAPPED') AND s.review_status = 'approved'")
    groups: dict[tuple, dict] = {}
    for r in rows:
        onset = as_date(r["onset_date"])
        key = (r["term"], r["exposure_label"] or "no recent exposure", _band(as_date(r["birth_date"]), onset), r["sex"] or "unknown")
        g = groups.setdefault(key, {"n": 0, "first": None})
        g["n"] += 1
        month = onset.strftime("%Y-%m") if onset else None
        if month and (g["first"] is None or month < g["first"]):
            g["first"] = month
    items = [{"term": t, "exposure_label": e, "age_band": a, "sex": s, "n_reports": _count(g["n"]),
              "first_month": g["first"] or "unknown"} for (t, e, a, s), g in sorted(groups.items())]
    return {"k": K, "items": items}
