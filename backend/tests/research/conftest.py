"""Fixtures: a fresh DuckDB with the dev pool and a few hand-written (synthetic) abstracts. LLM in stub mode."""
from __future__ import annotations

import pytest

from app import db as dbmod
from app.research import devpool, store
from app.schema import ensure_gov_schema

# Synthetic abstracts written for the tests (not real papers; real abstracts are never committed).
PAPERS = [
    dict(pmid="90000001", year=2021, title="Blood pressure after mRNA-1273 vaccination: a cohort study",
         abstract=("Background Post-marketing reports suggested blood pressure changes after vaccination. "
                   "Methods We followed 5,000 adults for 90 days after the first dose. "
                   "Results Hypertension onset was more frequent in adults over 40 after mRNA-1273 vaccination than in "
                   "unvaccinated controls. Fatigue and headache were common in the first two days. "
                   "Conclusions Clinicians should be aware of this signal and further studies are needed.")),
    dict(pmid="90000002", year=2024, title="No excess hypertension after Moderna vaccination in a registry",
         abstract=("Background Earlier cohort studies reported blood pressure signals after vaccination. "
                   "Methods We used a national registry with 2 million vaccinated people and matched controls. "
                   "Results Moderna vaccination was not associated with new hypertension diagnoses within 90 days. "
                   "Myocarditis was rare and mostly mild in young men after Moderna vaccination. "
                   "Conclusions The registry does not support a blood pressure signal.")),
    dict(pmid="90000003", year=2022, title="Myocarditis after BNT162b2 in adolescents",
         abstract=("Background Myocarditis has been reported after mRNA vaccines. "
                   "Methods We reviewed 300 adolescent cases from surveillance data across three countries. "
                   "Results Myocarditis after BNT162b2 occurred mostly after the second dose in male adolescents. "
                   "Most cases resolved within weeks with supportive care. "
                   "Conclusions The benefit of vaccination outweighs the risk in this group.")),
]


@pytest.fixture()
def db():
    store._schema_ready.clear()
    d = dbmod.DuckDB(":memory:")
    dbmod.set_db(d)
    ensure_gov_schema(d)
    devpool.create(d)
    store.ensure_schema(d)
    d.insert_rows("research.papers", [dict(
        paper_id=f"PMID:{p['pmid']}", pmid=p["pmid"], doi=None, title=p["title"], journal="Test Journal",
        pub_year=p["year"], abstract_text=p["abstract"], source_url=f"https://europepmc.org/article/MED/{p['pmid']}",
        query='"mRNA-1273" AND (adverse OR safety)', fetched_at=store.now()) for p in PAPERS])
    d.insert_rows("research.citations", [dict(edge_id="CIT-90000002-90000001", citing_paper_id="PMID:90000002",
                                              cited_paper_id="PMID:90000001")])
    yield d
    dbmod.set_db(None)
