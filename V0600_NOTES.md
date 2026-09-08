# v0.6.0 Production Candidate

Daemon-only production hardening. No application/CUSTOM/CV/salary/submit-click code changed.

- `MODE=--auto`: DRY_RUN preparation/repair lane then SUBMIT lane every cycle.
- `PREP_LIMIT=20`, `SUBMIT_LIMIT=20`, `INTERVAL=900`, no daily cap.
- Exclusive `flock` prevents concurrent autonomous agents.
- Brave/CDP and Ollama health checks with self-start attempts.
- `AGENT_SUBMIT_ARMED=YES` remains mandatory in daemon and jobs_loop.
- Circuit breaker exits 75 on repeated health/runtime failures or fresh ambiguous irreversible states. Historical ERROR backlog remains recoverable and does not stop production.
- systemd `RestartPreventExitStatus=42 64 75` prevents restart loops on login/safety/config stops.
- Installer backs up the old unit and old drop-ins before installing the clean v0.6.0 unit.
