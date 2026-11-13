"""Concept lookup and resolution for the knowledge graph.

Source of truth is Dev A's `ref.concepts` (codes from our Synthea data + hand synonyms). Until it exists, and to
make sure the research topics always have usable synonyms, we merge in a small hand-made list for the topics we
ingest. Codes in that list are standard CVX / SNOMED CT / RxNorm / LOINC codes; ref.concepts wins on labels.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.research import deps

# concept_id, label, synonyms (lowercase). Labels from ref.concepts override these.
FALLBACK_CONCEPTS: list[tuple[str, str, list[str]]] = [
    # exposures
    ("CVX:207", "SARS-COV-2 mRNA vaccine (Moderna)", ["moderna", "mrna-1273", "spikevax", "elasomeran"]),
    ("CVX:208", "SARS-COV-2 mRNA vaccine (Pfizer-BioNTech)", ["pfizer", "bnt162b2", "comirnaty", "tozinameran", "pfizer-biontech"]),
    ("CVX:210", "SARS-COV-2 vaccine (AstraZeneca)", ["astrazeneca", "chadox1", "chadox1 ncov-19", "azd1222", "vaxzevria"]),
    ("CVX:212", "SARS-COV-2 vaccine (Janssen)", ["janssen", "ad26.cov2.s", "johnson & johnson"]),
    ("CVX:213", "COVID-19 vaccine (any)", ["covid-19 vaccine", "covid-19 vaccines", "covid-19 vaccination",
                                                    "sars-cov-2 vaccine", "sars-cov-2 vaccines", "sars-cov-2 vaccination",
                                                    "covid vaccine", "covid-19 vaccinations"]),
    ("RXNORM:860975", "Metformin", ["metformin"]),
    # named but uncoded look-alikes, so "pulmonary hypertension" never resolves to essential hypertension
    ("FREE:pulmonary-hypertension", "Pulmonary hypertension", ["pulmonary hypertension", "pulmonary arterial hypertension",
                                                               "chronic thromboembolic pulmonary hypertension"]),
    ("FREE:intracranial-hypertension", "Intracranial hypertension", ["intracranial hypertension",
                                                                     "idiopathic intracranial hypertension",
                                                                     "isolated intracranial hypertension"]),
    ("FREE:pregnancy-induced-hypertension", "Pregnancy-induced hypertension", ["pregnancy-induced hypertension",
                                                                               "gestational hypertension"]),
    ("FREE:white-coat-hypertension", "White coat hypertension", ["white coat hypertension"]),
    ("FREE:hypertensive-anaphylaxis", "Hypertensive anaphylaxis", ["hypertensive anaphylaxis"]),
    # outcomes
    ("SNOMED:59621000", "Essential hypertension", ["hypertension", "high blood pressure", "hypertensive", "elevated blood pressure",
                                                  "blood pressure elevation", "increased blood pressure",
                                                  "increase in blood pressure", "blood pressure increase",
                                                  "rise in blood pressure"]),
    ("SNOMED:50920009", "Myocarditis", ["myocarditis"]),
    ("SNOMED:3238004", "Pericarditis", ["pericarditis"]),
    ("SNOMED:39579001", "Anaphylaxis", ["anaphylaxis", "anaphylactic reaction", "anaphylactic reactions"]),
    ("SNOMED:386661006", "Fever", ["fever", "pyrexia"]),
    ("SNOMED:84229001", "Fatigue", ["fatigue", "tiredness"]),
    ("SNOMED:25064002", "Headache", ["headache", "headaches"]),
    ("SNOMED:40956001", "Guillain-Barré syndrome", ["guillain-barré syndrome", "guillain-barre syndrome"]),
    ("SNOMED:193093009", "Bell's palsy", ["bell's palsy", "bell palsy", "facial palsy", "facial paralysis"]),
    ("SNOMED:60862001", "Tinnitus", ["tinnitus"]),
    ("SNOMED:302215000", "Thrombocytopenia", ["thrombocytopenia"]),
    ("SNOMED:22298006", "Myocardial infarction", ["myocardial infarction", "heart attack"]),
    ("SNOMED:230690007", "Stroke", ["stroke", "cerebrovascular accident"]),
    ("SNOMED:128053003", "Deep vein thrombosis", ["deep vein thrombosis", "deep venous thrombosis"]),
    ("SNOMED:59282003", "Pulmonary embolism", ["pulmonary embolism"]),
    ("SNOMED:30746006", "Lymphadenopathy", ["lymphadenopathy", "swollen lymph nodes"]),
    ("SNOMED:4740000", "Herpes zoster", ["herpes zoster", "shingles"]),
    ("SNOMED:111516008", "Blurred vision", ["blurred vision", "blurry vision"]),
    ("SNOMED:44054006", "Type 2 diabetes mellitus", ["type 2 diabetes", "type 2 diabetes mellitus", "t2dm"]),
    ("SNOMED:840539006", "COVID-19", ["covid-19", "sars-cov-2 infection"]),
    ("LOINC:4548-4", "Hemoglobin A1c", ["hba1c", "hemoglobin a1c", "glycated hemoglobin", "haemoglobin a1c"]),
]

EXPOSURE_SYSTEMS = {"CVX", "RXNORM"}
# CVX 213 ("SARS-CoV-2 vaccine, unspecified formulation") stands for "a COVID-19 vaccine" in papers that don't name the
# product. It is a class: the pool check counts any of its members, and the graph links members to it with IS_A.
CLASS_MEMBERS: dict[str, list[str]] = {"CVX:213": ["CVX:207", "CVX:208", "CVX:210", "CVX:212", "CVX:213"]}
_SUFFIX = re.compile(r"\s*\((disorder|finding|procedure|situation|substance|product|observable entity|morphologic abnormality)\)\s*$", re.I)


@dataclass
class Concept:
    concept_id: str
    label: str
    synonyms: list[str] = field(default_factory=list)

    @property
    def code_system(self) -> str:
        return self.concept_id.split(":", 1)[0]

    @property
    def code(self) -> str:
        return self.concept_id.split(":", 1)[1]

    @property
    def is_exposure(self) -> bool:
        return self.code_system in EXPOSURE_SYSTEMS

    def terms(self) -> list[str]:
        base = _SUFFIX.sub("", self.label).strip().lower()
        out = [base] if base else []
        out += [s for s in self.synonyms if s and s not in out]
        return out


class ConceptIndex:
    def __init__(self, concepts: dict[str, Concept]):
        self.by_id = concepts
        self.by_term: dict[str, str] = {}
        for c in concepts.values():
            for t in c.terms():
                self.by_term.setdefault(normalise(t), c.concept_id)
        # longest terms first so "covid-19 vaccine" wins over "covid-19"
        terms = sorted(self.by_term, key=len, reverse=True)
        self._pattern = re.compile(
            r"(?<![\w-])(" + "|".join(re.escape(t) for t in terms if len(t) >= 3) + r")(?![\w-])", re.I
        ) if terms else None

    def resolve(self, text: str) -> str:
        """Map an entity string to a concept ID, or FREE:<slug>."""
        key = normalise(text)
        if key in self.by_term:
            return self.by_term[key]
        return "FREE:" + slug(text)

    def find(self, sentence: str) -> list[tuple[str, str, int]]:
        """Non-overlapping (concept_id, matched_text, start) found in a sentence, in order."""
        if not self._pattern:
            return []
        return [(self.by_term[normalise(m.group(1))], m.group(1), m.start()) for m in self._pattern.finditer(sentence)]

    def get(self, concept_id: str) -> Concept | None:
        return self.by_id.get(concept_id)

    def label(self, concept_id: str) -> str:
        c = self.by_id.get(concept_id)
        if c:
            return c.label
        return concept_id.split(":", 1)[-1].replace("-", " ")

    def terms_for(self, concept_id: str, raw: str | None = None) -> list[str]:
        c = self.by_id.get(concept_id)
        terms = c.terms() if c else []
        if raw:
            terms = [raw.lower()] + terms
        if concept_id.startswith("FREE:") and not raw:
            terms.append(concept_id[5:].replace("-", " "))
        return terms


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("’", "'").strip().lower())


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", normalise(text)).strip("-")[:60] or "unknown"


def load_index(db=None) -> ConceptIndex:
    db = db or deps.get_db()
    concepts: dict[str, Concept] = {}
    if deps.table_exists(db, "ref.concepts"):
        for r in db.query("SELECT concept_id, label, synonyms FROM ref.concepts"):
            syns = [normalise(s) for s in (r.get("synonyms") or "").split(";") if s.strip()]
            concepts[r["concept_id"]] = Concept(r["concept_id"], r.get("label") or r["concept_id"], syns)
    for cid, label, syns in FALLBACK_CONCEPTS:
        if cid in concepts:
            have = concepts[cid].synonyms
            concepts[cid].synonyms = have + [s for s in syns if s not in have]
        else:
            concepts[cid] = Concept(cid, label, list(syns))
    return ConceptIndex(concepts)
