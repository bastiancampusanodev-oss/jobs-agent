# Job Agent v0.5.30 — HUMAN_REVIEW recovery + observability truth

## Why this patch exists

The v0.5.29 SRE dry-run proved two things:

1. Legacy `REQUEUE_FORM_INVALID` rows created before v0.5.29 may no longer expose the original rejected Get on Board step after the browser has returned to REVIEW. A REVIEW page is not evidence that the failed editable step was BASIC/CUSTOM/PROFILE.
2. The SRE form correctly stopped at HUMAN_REVIEW for the observability-tools question because `candidate.yaml` did not contain the user's named production observability stack.

## Changes

- `scripts/jobs_loop.py`
  - Explicit `--url --dry-run` may re-open a `HUMAN_REVIEW` row; normal backlog still skips HUMAN_REVIEW.
  - Such a targeted retry is forced through REPAIR MODE, never directly trusted as READY.
- `HUMAN_REVIEW` with empty `last_error` is treated as a CUSTOM-field blocker (the only no-error HUMAN_REVIEW emitted by `complete_application`) and resumes with `repair_step=custom`, correcting the legacy SRE fallback without manual SQLite edits.
  - If HUMAN_REVIEW occurs in CUSTOM during REPAIR MODE, persist:
    - `form_constraints.repair_step = custom`
    - `form_constraints.repair_step_source = human_blocker`
  - A legacy REVIEW page with no canonical GOB step now uses BASIC only as a conservative entry point and does not falsely label that fallback as server-learned evidence.
- `config/candidate.yaml`
  - Adds documented operational use of Grafana, Splunk and Instana in the BancoEstado production/observability context.
- `src/agentes/jobs/technical_answer_engine.py`
  - Adds Grafana/Splunk/Instana observability truth handling.
  - Produces a qualified answer: operational use is stated; implementation/administration ownership for unsupported tools is not claimed.
- `src/agentes/jobs/application_runner.py`
  - Structured technical partial answers now take priority over raw RAG for technical composite questions, preventing a retrieved fragment from erasing qualifiers.
- `tests/test_observability_truth.py`
  - Verifies confirmed vs unknown observability tools and the safe composite answer.

## Expected SRE answer

`Mi experiencia directa es de uso operativo: he trabajado con Grafana, Splunk e Instana para monitoreo de producción, observabilidad, análisis de logs/trazabilidad y respuesta a incidentes. No tengo evidencia suficiente para afirmar implementación o administración directa de OpenTelemetry, Zabbix y Wazuh, por lo que no atribuyo ese alcance a mi experiencia.`

## Safety properties retained

- `--submit` still requires `AGENT_SUBMIT_ARMED=YES`.
- Only `DRY_RUN_READY` can enter submit mode.
- HUMAN_REVIEW can only be re-evaluated through explicit `--url` in DRY RUN.
- SUBMITTED / ALREADY_APPLIED / SKIP / REVIEW remain terminal for this retry mechanism.
- No retry of the irreversible final submit click is introduced.
