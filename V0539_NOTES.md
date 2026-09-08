# v0.5.39 — QA custom semantic safety

Purpose: prevent false-positive DRY_RUN_READY when a technical/evidence answer does not semantically answer the CUSTOM question.

Changes:
- Added conservative QA-specific grounded answers for recurring QA tool/agile/API/database/formal-years questions.
- `Azure DevOps` inside QA/agile questions no longer activates generic Azure/cloud answers.
- Weak extractive evidence must cover a larger fraction of a multi-concept question; tag clouds cannot authorize a CUSTOM answer.
- Formal QA years remain 0 unless explicit QA-role evidence is added; adjacent systems/dev/operations experience is described as related, not QA-direct.
- Submit/click/state/systemd logic unchanged.

Validation: 51 tests passed.
