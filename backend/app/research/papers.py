"""Paper ingestion from Europe PMC (free REST API, no key) into research.papers + research.citations.

Raw JSON is cached under data/papers/ (git-ignored: abstracts are copyrighted, never commit them).
Once the cache is filled, the build runs offline from it.

    python -m app.research.papers --topic covid_vaccine_safety            # fetch what's missing, then load
    python -m app.research.papers --topic covid_vaccine_safety --offline  # cache only
"""
from __future__ import annotations

import argparse
import html
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

from app.research import deps, store

API = "https://www.ebi.ac.uk/europepmc/webservices/rest"
CACHE = deps.REPO_ROOT / "data" / "papers"
USER_AGENT = "TrustLens-hackathon/0.1 (research prototype)"

# Each query runs twice: newest first and most cited first, so the graph mixes old and recent research.
TOPICS: dict[str, list[str]] = {
    "covid_vaccine_safety": [
        '"mRNA-1273" AND (adverse OR safety)',
        '"BNT162b2" AND (adverse OR safety)',
        '"COVID-19 vaccine" AND hypertension',
        'TITLE:(hypertension OR "blood pressure") AND TITLE:(vaccin*) AND (COVID-19 OR SARS-CoV-2)',
        'ABSTRACT:("mRNA-1273" OR moderna) AND ABSTRACT:(hypertension OR "blood pressure")',
        '"COVID-19 vaccine" AND myocarditis',
    ],
    "metformin_t2dm": [
        'metformin AND "type 2 diabetes" AND HbA1c',
    ],
}
SORTS = ["P_PDATE_D desc", "CITED desc"]


# ------------------------------------------------------------------------------------------ fetch


def _get_json(url: str, retries: int = 3) -> dict:
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001 - retried, then re-raised
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Europe PMC request failed: {url}: {last}")


def _cache_file(*parts: str) -> Path:
    return CACHE.joinpath(*parts)


def search(query: str, sort: str, page_size: int, topic: str, refresh=False, offline=False) -> list[dict]:
    path = _cache_file(topic, f"search-{store.short_hash(query, sort, str(page_size), n=10)}.json")
    if path.exists() and not refresh:
        return json.loads(path.read_text())["response"].get("resultList", {}).get("result", [])
    if offline:
        return []
    full_query = f"({query}) AND SRC:MED AND HAS_ABSTRACT:y"
    url = f"{API}/search?" + urllib.parse.urlencode(
        dict(query=full_query, format="json", resultType="core", pageSize=page_size, sort=sort))
    data = _get_json(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"query": query, "sort": sort, "url": url, "response": data}))
    time.sleep(0.2)
    return data.get("resultList", {}).get("result", [])


def references(pmid: str, refresh=False, offline=False) -> list[str]:
    """PMIDs this paper cites (MED source only)."""
    path = _cache_file("refs", f"{pmid}.json")
    if path.exists() and not refresh:
        data = json.loads(path.read_text())
    elif offline:
        return []
    else:
        try:
            data = _get_json(f"{API}/MED/{pmid}/references?format=json&pageSize=1000")
        except RuntimeError:
            return []
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
        time.sleep(0.1)
    refs = (data.get("referenceList") or {}).get("reference") or []
    return [str(r["id"]) for r in refs if r.get("source") == "MED" and r.get("id")]


# ------------------------------------------------------------------------------------------ parse

_BLOCK_TAGS = re.compile(r"</?(h\d|p|br|div|li|ul|ol|section|title)[^>]*>", re.I)
_TAGS = re.compile(r"<[^>]+>")


def clean_abstract(raw: str) -> str:
    """Europe PMC abstracts contain HTML (<h4>, <i>, <sup>). Store plain text so quotes can be checked verbatim."""
    text = _BLOCK_TAGS.sub(" ", raw or "")
    text = _TAGS.sub("", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def to_paper(rec: dict, query: str) -> dict | None:
    pmid = str(rec.get("pmid") or "").strip()
    abstract = clean_abstract(rec.get("abstractText") or "")
    if not pmid or len(abstract) < 200:
        return None
    journal = ((rec.get("journalInfo") or {}).get("journal") or {}).get("title") or rec.get("journalTitle")
    year = rec.get("pubYear")
    return dict(
        paper_id=f"PMID:{pmid}", pmid=pmid, doi=rec.get("doi"), title=clean_abstract(rec.get("title") or ""),
        journal=journal, pub_year=int(year) if str(year or "").isdigit() else None, abstract_text=abstract,
        source_url=f"https://europepmc.org/article/MED/{pmid}", query=query, fetched_at=store.now())


# ------------------------------------------------------------------------------------------- load


def ingest(topic: str = "covid_vaccine_safety", page_size: int = 40, refresh=False, offline=False,
           with_references=True, db=None) -> dict:
    if topic not in TOPICS:
        raise ValueError(f"unknown topic {topic!r}; known: {sorted(TOPICS)}")
    db = db or deps.get_db()
    store.ensure_schema(db)
    papers: dict[str, dict] = {}
    for query in TOPICS[topic]:
        for sort in SORTS:
            for rec in search(query, sort, page_size, topic, refresh=refresh, offline=offline):
                p = to_paper(rec, query)
                if p and p["paper_id"] not in papers:
                    papers[p["paper_id"]] = p
    rows = list(papers.values())
    if rows:
        _delete_in(db, "research.papers", "paper_id", [r["paper_id"] for r in rows])
        db.insert_rows("research.papers", rows)

    n_cit = 0
    if with_references and rows:
        in_corpus = {r["pmid"] for r in db.query("SELECT pmid FROM research.papers")}
        cit_rows = []
        for p in rows:
            for ref in sorted(set(references(p["pmid"], refresh=refresh, offline=offline))):
                if ref in in_corpus and ref != p["pmid"]:
                    cit_rows.append(dict(edge_id=f"CIT-{p['pmid']}-{ref}", citing_paper_id=p["paper_id"],
                                         cited_paper_id=f"PMID:{ref}"))
        _delete_in(db, "research.citations", "citing_paper_id", [p["paper_id"] for p in rows])
        db.insert_rows("research.citations", cit_rows)
        n_cit = len(cit_rows)

    for p in rows:
        deps.lineage_add(p["paper_id"], "paper", [(p["source_url"], "europepmc")], "papers.py:ingest")
    years = [r["pub_year"] for r in rows if r["pub_year"]]
    summary = dict(topic=topic, papers=len(rows), citations=n_cit, offline=offline,
                   years=[min(years), max(years)] if years else None)
    summary["audit_seq"] = deps.audit_append("papers.py", "data.loaded", "research.papers", summary)
    return summary


def _delete_in(db, table: str, col: str, values: list[str], chunk: int = 200) -> None:
    for i in range(0, len(values), chunk):
        part = values[i:i + chunk]
        db.execute(f"DELETE FROM {table} WHERE {col} IN ({', '.join('?' for _ in part)})", part)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--topic", default="covid_vaccine_safety", choices=sorted(TOPICS))
    ap.add_argument("--page-size", type=int, default=40)
    ap.add_argument("--refresh", action="store_true", help="refetch even if cached")
    ap.add_argument("--offline", action="store_true", help="use the cache only")
    ap.add_argument("--no-references", action="store_true")
    a = ap.parse_args()
    print(json.dumps(ingest(a.topic, a.page_size, a.refresh, a.offline, not a.no_references), indent=2, default=str))


if __name__ == "__main__":
    main()
