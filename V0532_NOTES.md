# v0.5.32 — legacy draft revalidation guardrail

## Why

Old backlog rows may resume directly at Get on Board REVIEW. A normal dry-run previously marked those rows DRY_RUN_READY without replaying editable fields through the current CandidateTruth/answer engine.

## Change

Adds explicit `--revalidate` mode.

Safety contract:

- allowed only with `--dry-run --url`
- rejected with `--submit`
- rejected without an explicit target URL
- never runs as a bulk backlog mode
- an existing `DRY_RUN_READY` target is reopened only when `--revalidate` is explicitly present
- revalidation starts from Get on Board `experience` and uses the existing REPAIR MODE state machine
- `complete_application(..., repair_mode=True)` requires at least one editable stage before returning `DRY_RUN_READY`
- HUMAN_REVIEW remains a blocker when current CandidateTruth cannot answer safely
- no submit/click logic changed

## Validation

- `python -m py_compile`: PASS
- pytest: 13 passed
