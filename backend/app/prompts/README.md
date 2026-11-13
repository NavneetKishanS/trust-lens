# Prompts

One file per LLM purpose (e.g. `summary_patient.md`, `verifier.md`, `kg_establish.md`). `llm.call` fills `{{name}}`
placeholders and records `sha256(file)` as `prompt_hash` in lineage and `gov.llm_calls`, so keep prompts here, not inline.
