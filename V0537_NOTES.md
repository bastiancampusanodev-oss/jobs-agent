# v0.5.37 — Known facts, CLP salary, grounded CUSTOM

- RUT possession and Chile work authorization are deterministic facts.
- Actual RUT number remains HUMAN_REVIEW unless explicitly stored.
- Liquid/net CLP salary uses configurable approximate conversion from the already validated USD salary.
  - default 950 CLP/USD
  - rounds to nearest 50,000 CLP
  - override with AGENT_USD_CLP_APPROX_RATE / AGENT_CLP_ROUND_TO
- Custom motivation reuses the deterministic motivation engine.
- Generic QA role-experience question is answered from documented experience and explicitly avoids claiming a formal QA title.
- Ollama fallback remains fail-closed and now defaults to llama3.2:1b with a smaller context for local latency.
- Submit/click/state/systemd logic unchanged.
