# Job Agent v0.5.31 — CUSTOM technical routing fix

## Root cause

The v0.5.30 observability answer engine was correct, but `application_runner.py` did not classify the exact Get on Board wording `herramientas ... implementado y administrado` as a technical question. Therefore the partial technical answer engine was never called and the required field fell through to HUMAN_REVIEW.

## Fix

- Centralizes technical-question routing markers in `technical_answer_engine.py`.
- Recognizes ownership/action wording such as `implementado`, `administrado`, `implemented`, `administered`, plus explicit observability-tool wording.
- Uses the same classifier for text fields and select/radio technical questions.
- Keeps CandidateTruth qualification intact: operational Grafana/Splunk/Instana use is not upgraded into implementation/administration ownership.
- Adds a regression test for the exact SRE question.

## Safety

No submit semantics, status eligibility, click logic, systemd configuration, salary logic, or database schema were changed.
