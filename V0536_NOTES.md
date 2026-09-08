# v0.5.36 — Fast native Ollama CUSTOM fallback

## Problema observado
v0.5.35 fallaba cerrado con `APITimeoutError` al resolver CUSTOM mediante
el Agents SDK/OpenAI-compatible path. En un equipo CPU-only el fallback podía
hacer varias vueltas con un prompt más grande de lo necesario.

## Cambio
- CUSTOM fallback sigue siendo local-only y grounded.
- Se elimina el Agents SDK sólo de este fallback.
- Una sola llamada nativa a `Ollama /api/chat`.
- Structured output con JSON Schema de `GroundedFallbackAnswers`.
- Prompt compacto: grounding 9k chars, job 3.5k, fields 5k.
- `temperature=0`, `seed=42`, `num_ctx=8192`, `num_predict=650`.
- `AGENT_CUSTOM_LLM_MODEL` permite modelo dedicado; default `AGENT_MODEL`.
- `AGENT_CUSTOM_LLM_TIMEOUT` permite timeout dedicado; default 120 s.
- Nunca usa cloud si `AGENT_LLM_PROVIDER != ollama`.
- Conserva validación determinista de evidence_quotes, options y conservative_no.
- Conserva fail-closed: cualquier error => HUMAN_REVIEW.
- Logging de model/fields/prompt chars/tokens/output tokens/elapsed.

## No cambia
- submit / click final
- estados y repair_step
- CandidateTruth guardrails
- salary engine
- systemd/daemon

## Tests
34 passed.
