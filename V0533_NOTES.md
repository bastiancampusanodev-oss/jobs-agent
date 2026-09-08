# v0.5.33 — deterministic CV-language guardrail

## Why
A legacy IA Engineer / Niuro decision carried `cv_id=01_ES` even though the current vacancy is English. `--revalidate` correctly regenerated PROFILE and motivation in English, but reused the stale Spanish CV id.

## Changes
- New `cv_language_policy.py` uses the current vacancy language plus `config/cvs.yaml`.
- Preserves the CV family/profile chosen by the decision engine.
- Deterministically swaps only the language pair (for example `01_ES -> 02_EN`).
- In DRY RUN, a mismatch forces an editable repair from `experience`, ensuring BASIC actually selects the corrected CV before REVIEW.
- In SUBMIT, a mismatch blocks before any click and stores `CV_LANGUAGE_MISMATCH`; the draft must first pass a dry-run/revalidation.
- No submit/click code changed.

## Safety
The LLM may choose the role family, but it no longer has final authority over ES/EN CV language.
