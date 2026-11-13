# TrustLens: Architecture (v2, MVP)

**Every AI sentence is backed by data you can click through to, checked by other agents, and signed off by a human where it matters.**

## 1. System overview

```mermaid
flowchart LR
    subgraph USERS["Users"]
        PT["Patient"]
        PH["Physician"]
        RS["Researcher"]
        CL["Clinician reviewer"]
    end

    subgraph API["FastAPI service (Swagger until H11, then Next.js)"]
        subgraph CLIN["Clinical engine"]
            FACTS["Facts<br/>SQL computes"]
            GEN["Generator<br/>LLM phrases"]
            CRIT["Critic<br/>deterministic"]
            VER["Verifier<br/>LLM entailment"]
            SYM["Symptom intake<br/>extract, map, classify"]
        end
        subgraph RES["Research engine"]
            A1["A1 Establisher<br/>relations + verbatim quote"]
            A2["A2 Critic<br/>quote and entity checks"]
            A3["A3 Sanity<br/>literature + pool check"]
            ASK["Ask the data<br/>NL to SQL, guard,<br/>k-anon, cited summary"]
        end
        subgraph GOV["Governance"]
            RQ["Review queue"]
            AUD["Audit hash chain"]
            LIN["Lineage"]
        end
    end

    subgraph EX["Exasol on AWS eu-central-1 (DuckDB fallback)"]
        CUR[("curated<br/>Synthea EHR")]
        REF[("ref<br/>lab ranges, known effects,<br/>vocab, concepts")]
        COM[("community<br/>reports, symptoms")]
        POOL[("pool<br/>anonymised views")]
        RSD[("research<br/>papers, edges, asks")]
        GOVD[("gov<br/>audit, lineage, llm calls")]
    end

    SYN["Synthea CSV<br/>~1,000 synthetic patients"] --> CUR
    EPMC["Europe PMC REST<br/>papers + references"] --> RSD
    LLM["Claude Opus 5.5<br/>Bedrock EU / API / stub"]

    PT --> GEN
    PT --> SYM
    PH --> GEN
    RS --> ASK
    RS --> A3
    CL --> RQ

    CUR --> FACTS --> GEN --> CRIT --> VER
    CRIT -- flag --> RQ
    VER -- unsupported --> RQ
    SYM -- NEW --> RQ
    RQ -- approved --> COM
    COM --> POOL
    CUR --> POOL
    POOL --> ASK
    POOL --> A3
    RSD --> A1 --> A2 --> A3 --> RSD

    GEN -. phrase .-> LLM
    VER -. check .-> LLM
    SYM -. extract .-> LLM
    A1 -. extract .-> LLM
    ASK -. SQL + summary .-> LLM

    CLIN --> AUD
    RES --> AUD
    RQ --> AUD
    AUD --> GOVD
    LIN --> GOVD
```

## 2. Evidence-backed summary (patient and physician)

```mermaid
flowchart LR
    ROWS["Synthea rows<br/>OBS, ENC, MED, IMM, CPL"] --> F["facts.sql<br/>lab trends vs ranges,<br/>visits, meds, care plans"]
    F --> G["Generator (LLM)<br/>sentences citing fact IDs"]
    G --> C{"Critic<br/>facts exist? numbers match?<br/>dates match? banned phrases?"}
    C -- pass --> V{"Verifier (LLM)<br/>facts support sentence?"}
    C -- flag --> Q["Clinician review queue"]
    V -- supported --> OK["Verified sentence"]
    V -- unsupported / unsure --> Q
    OK --> P["Patient view<br/>plain words, no diagnoses"]
    OK --> D["Physician view<br/>codes + lineage"]
    Q -. hidden from patient until approved .-> P
```

## 3. Patient symptom loop

```mermaid
flowchart LR
    T["Patient writes:<br/>tired, headache, blurred vision"] --> X["Extract (LLM)<br/>span must be verbatim"]
    X --> M["Map to symptom vocabulary"]
    M --> K{"Known side effect of a<br/>vaccine/medicine they got,<br/>within window?"}
    K -- yes --> E["EXPECTED<br/>recorded for stats"]
    K -- no --> R{"Already in the<br/>doctor's record?"}
    R -- yes --> I["IN_RECORD<br/>recorded for stats"]
    R -- no --> N["NEW<br/>pending clinician review"]
    N -- approve --> RARE["Research pool:<br/>validated rare case"]
    N -- reject --> X2["Kept out, audited"]
```

## 4. Research knowledge graph

```mermaid
flowchart LR
    P["Europe PMC papers<br/>old and recent"] --> A1["A1 Establisher (LLM)<br/>subject, relation, object,<br/>verbatim quote"]
    P --> CIT["Citation edges<br/>paper cites paper"]
    A1 --> A2{"A2 Critic<br/>quote verbatim?<br/>entities in quote?<br/>negation matches?"}
    A2 -- fail --> REJ["Rejected edge<br/>kept for audit"]
    A2 -- pass --> A3["A3 Sanity<br/>other papers agree or contradict?<br/>visible in our anonymised pool?"]
    A3 --> E["Accepted edge<br/>quote + paper link +<br/>CONSISTENT / CONTESTED / SINGLE_SOURCE<br/>OBSERVED / NOT_OBSERVED / UNTESTABLE"]
```

## 5. Ask the data

```mermaid
sequenceDiagram
    actor R as Researcher
    participant API as Ask the data
    participant LLM as Claude
    participant G as SQL guard
    participant DB as Exasol pool views
    participant AU as Audit

    R->>API: "Is hypertension onset more common after Moderna in patients over 40?"
    API->>API: Template match (demo-safe path)
    API->>LLM: Otherwise generate SQL from pool schema
    LLM-->>API: SELECT ...
    API->>G: One SELECT, pool.* only, no identifiers, LIMIT
    alt unsafe
        G-->>API: blocked
        API->>AU: ask.blocked
    else safe
        API->>DB: run read-only
        DB-->>API: rows
        API->>API: suppress counts under 5, sufficiency verdict
        API->>LLM: summarise rows only, cite cells
        API->>API: critic: numbers match cells, no causal words
        API->>AU: ask.answered
        API-->>R: SQL + table + verdict + cited summary
    end
```

## Design principles

| Principle | How |
|---|---|
| Evidence-backed | SQL computes facts; the LLM only phrases them. Graph edges need a verbatim quote |
| The LLM never decides | Critics, classification, verdicts and k-anonymity are deterministic rules |
| Multi-agent governance | Producer → critic → sanity/verifier; disagreements go to a human |
| Audited lineage | Every sentence, symptom, edge and answer traces to rows or papers, plus agent, model and prompt hash; hash-chained audit log |
| Privacy | Researchers only see anonymised views; counts under 5 shown as "<5"; synthetic data only |
| Honest demo | The planted research signal is labelled synthetic everywhere |
