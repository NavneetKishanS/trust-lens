# TrustLens: Architecture

**Before the AI answers, it checks whether the data can answer.**

## 1. System overview

```mermaid
flowchart LR
    subgraph USERS["Users"]
        R["Researcher"]
        P["Physician"]
        PT["Patient"]
        C["Clinician reviewer"]
    end

    subgraph FE["Frontend: Next.js"]
        RV["Research stepper<br/>Understand, Validate, Verdict, Approve, Analyse"]
        PV["Physician summary<br/>cited claims + timeline"]
        PTV["Patient overview<br/>plain language + diary"]
        RQ["Review queue"]
        TV["Lineage drawer · Audit chain · Evals"]
    end

    subgraph BE["Backend: FastAPI"]
        subgraph TE["Trust engine"]
            PL["Planner<br/>question to requirements"]
            VA["Validator<br/>runs 9 SQL checks"]
            VD["Verdict rules<br/>deterministic"]
            AN["Analysis + report"]
        end
        subgraph AG["Agent loop"]
            GEN["Generator<br/>drafts cited claims"]
            CR["Critic<br/>deterministic checks"]
            VE["Verifier<br/>entailment"]
        end
        OV["Oversight<br/>human approval"]
        AU["Audit log<br/>SHA-256 hash chain"]
        LI["Lineage tracker"]
        EV["Eval harness<br/>seeded defects"]
    end

    subgraph EX["Exasol Personal on AWS eu-central-1"]
        RAW[("raw")]
        CUR[("curated")]
        VAL[("validation")]
        LIN[("lineage")]
        AUD[("audit")]
        COM[("community")]
        AGT[("agents")]
        EVS[("evals")]
    end

    subgraph EXT["External services"]
        LLM["Claude Opus 5.5<br/>Bedrock / Anthropic API / stub"]
        TTS["ElevenLabs TTS<br/>optional"]
    end

    GEN_DATA["Synthetic cohort<br/>240 patients, 3 labs,<br/>9 seeded defects"] --> RAW
    RAW --> CUR

    R --> RV
    P --> PV
    PT --> PTV
    C --> RQ

    FE -- REST --> BE

    PL --> VA --> VD --> OV --> AN
    GEN --> CR --> VE --> OV

    VA -- SQL --> VAL
    VA -- SQL --> CUR
    AN -- SQL --> CUR
    GEN -- reads --> CUR
    OV --> AGT
    OV --> COM
    AU --> AUD
    LI --> LIN
    EV --> EVS

    PL -. extract .-> LLM
    VD -. explain only .-> LLM
    GEN -. draft .-> LLM
    VE -. check .-> LLM
    PTV -. voice .-> TTS
```

## 2. Trust flow (researcher)

```mermaid
sequenceDiagram
    actor R as Researcher
    participant UI as Next.js UI
    participant API as FastAPI trust engine
    participant DB as Exasol
    participant LLM as Claude
    participant AU as Audit chain

    R->>UI: "Can we analyse HbA1c change across labs?"
    UI->>API: POST /research/runs
    API->>LLM: Extract requirements (structured output)
    LLM-->>API: labs, LOINC codes, units, period
    API->>AU: run.created
    UI->>API: POST /research/runs/{id}/validate
    API->>DB: 9 validation checks per lab (SQL)
    DB-->>API: PASS / WARN / FAIL + evidence rows
    API->>API: Verdict rules decide (no LLM)
    API->>LLM: Explain verdict, cite check IDs only
    LLM-->>API: Explanation (cited IDs verified against DB)
    API->>AU: run.validated
    API-->>UI: CONDITIONAL + limitations + evidence SQL
    R->>UI: Accept / reject each limitation
    UI->>API: POST /research/runs/{id}/approve
    API->>AU: run.approved
    UI->>API: GET /research/runs/{id}/analysis
    API->>DB: Analysis on permitted labs, stratified
    API->>AU: analysis.generated
    API-->>UI: Trend chart + report + lineage
```

## 3. Agent loop (physician / patient)

```mermaid
flowchart LR
    ROWS["Patient rows since last visit"] --> GEN["Generator<br/>LLM drafts claims<br/>with row citations"]
    GEN --> CR{"Critic<br/>citations exist?<br/>numbers match?<br/>dates match?"}
    CR -- pass --> VE{"Verifier<br/>do the rows<br/>support the claim?"}
    CR -- flag --> RQ["Clinician review queue"]
    VE -- supported --> OK["Verified claim<br/>shown with sources"]
    VE -- not supported --> RQ
    RQ -- approve / reject --> OK
    OK --> PHY["Physician summary"]
    OK --> PAT["Patient overview<br/>plain language, caveats kept"]
    RQ -.-> AU[("Audit chain")]
    OK -.-> LIN[("Lineage<br/>source file, row, model, prompt hash")]
```

## Design principles

| Principle | How |
|---|---|
| Data before answers | Deterministic SQL checks in Exasol run before any analysis |
| The LLM never decides | Rules pick the verdict; Claude only extracts, explains and drafts, and every output is validated against the DB |
| Human in the loop | Researchers approve limitations; clinicians review flagged claims and patient reports |
| Every claim traceable | Lineage from source file to raw row to transform to model and prompt hash to claim |
| Tamper-evident | Hash-chained audit log, verifiable in one click |
| Privacy | Synthetic data only; k-anonymity (counts under 5 shown as "<5") in the community pool |
| Measured, not claimed | Seeded-defect evals: how many of the 9 known problems we catch |
