# v0.6.1 Production hotfix

- Removes external `sqlite3` CLI dependency from `jobs_daemon.sh`; status counters use Python stdlib `sqlite3` read-only queries.
- Sets a deterministic PATH for systemd/daemon runtime.
- Adds exit code 70 to `RestartPreventExitStatus` so missing/config dependencies stop safely instead of restart-looping.
- Archives the previous systemd log on install so v0.6.1 startup is easy to inspect without historical OpenAI 429 noise.
- Keeps production settings: AUTO two-lane, PREP_LIMIT=20, SUBMIT_LIMIT=20, INTERVAL=900, no daily cap, AGENT_SUBMIT_ARMED=YES.
