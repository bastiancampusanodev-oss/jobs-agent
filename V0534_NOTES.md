# v0.5.34 — unified application language policy

- Adds `job_language_policy.detect_job_language()` as the single source of truth.
- Explicit Get on Board instructions such as `Requires applying in English` / `Requiere postular en inglés` override localized UI text.
- PROFILE, Motivation and CV language alignment now use the same detector.
- Prevents mixed runs such as PROFILE ES + CV ES + Motivation EN on an English-required vacancy.
- No submit/click/state-machine/systemd behavior changed.
