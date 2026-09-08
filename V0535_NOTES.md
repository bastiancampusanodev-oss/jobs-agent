# v0.5.35 — Grounded Ollama CUSTOM fallback

- Keeps existing priority: deterministic → CandidateTruth/RAG → local Ollama → HUMAN_REVIEW.
- Ollama receives only unresolved CUSTOM fields plus candidate/rules/relevant personal knowledge.
- Job text is context, never evidence of candidate experience.
- Positive factual answers require verbatim evidence quotes that are deterministically found in grounding.
- Unknown technical experience may use a conservative "not documented in my current profile" answer.
- Ambiguous labels, personal/sensitive data, legal consent, and unresolved salary/CLP fields remain HUMAN_REVIEW.
- Select/radio output must match a visible option.
- Ollama errors fail closed to the original HUMAN_REVIEW answer.
- Adds explicit preferences for all contract types, fixed-term, project-based and hourly work to application_rules.yaml.
