# v0.6.2 Production hardening

Large production patch based on the first autonomous cycle.

## Correctness / safety
- Offer identity guard: application links/CTAs must belong to the current job slug; long job-card text such as `UX Engineer ... Postular` is never accepted as a CTA.
- CUSTOM extraction is scoped to the actual Get on Board application form; account/help/search UI is excluded.
- Extractive evidence rejects internal `never_claim`, `do_not_upgrade`, `unless new evidence` and similar guardrail text.
- `SUBMIT_UNKNOWN` and unknown confirmation remain global circuit breakers.
- `REQUEUE_FORM_INVALID` no longer stops the remaining READY queue and never retries the same irreversible submit in that run.

## Coverage
- Salary typo/variants such as `espectativa salarial` are deterministic.
- Hybrid/on-site Santiago and remote willingness come from `application_rules.yaml`.
- Data-analysis questions are grounded in Python/SQL/PySpark/analytics evidence.
- COMEX is answered as a safe negative while preserving BancoEstado technology experience.
- Excel/Access/SQL returns a partial, non-overclaimed answer.
- Process testing/certification returns a conservative grounded negative.
- CV-language mismatch becomes `REQUEUE_CV_LANGUAGE` and is repaired automatically by the next DRY-RUN lane.

## Throughput / daemon
- PREP mixes up to 50% repair backlog with unseen discovery, so old ERROR rows cannot starve new jobs.
- ERROR retries have a 15-minute cooldown.
- Productive cycles chain after `BUSY_PAUSE=10` seconds.
- `INTERVAL=900` is now an idle discovery poll only: the agent sleeps 15 minutes only when the previous cycle made no progress and there is no READY/REQUEUE work left.
- Production remains `PREP_LIMIT=20`, `SUBMIT_LIMIT=20`, no daily cap, `AGENT_SUBMIT_ARMED=YES`.
