You extract relations between clinical entities from one research abstract for a knowledge graph.
A second, strict program will check every relation you return. It rejects a relation when:
- the quote is not copied character for character from the abstract,
- the subject or the object does not appear in the quote,
- the relation is NO_ASSOCIATION_WITH and the quote has no negation ("no", "not", "did not"), or the relation is
  positive and the quote does contain a negation.

Rules:
- Return at most 5 relations. Fewer, well-supported relations are better than many weak ones. Return none if the abstract states no clear relation.
- `relation` must be exactly one of: ASSOCIATED_WITH, INCREASES_RISK_OF, DECREASES_RISK_OF, ADVERSE_EVENT_OF, TREATS, NO_ASSOCIATION_WITH.
  - ADVERSE_EVENT_OF: subject is the adverse event, object is the vaccine or drug.
  - INCREASES_RISK_OF / DECREASES_RISK_OF / TREATS: subject is the exposure (vaccine, drug), object is the outcome.
  - NO_ASSOCIATION_WITH: the abstract explicitly reports no association.
- `subject` and `object` are short entity names written exactly as they appear in the quote (e.g. "mRNA-1273", "myocarditis",
  "hypertension"). Prefer these known concepts when they fit: {{concept_hints}}.
- `quote` is ONE complete sentence copied verbatim from the abstract that states the relation. Do not paraphrase, shorten, merge sentences or fix typos.
- Report what the paper states. Do not add knowledge from outside the abstract.

Title: {{title}}

Abstract:
<<<
{{abstract}}
>>>
