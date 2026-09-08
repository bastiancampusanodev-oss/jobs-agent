#!/usr/bin/env bash
set -euo pipefail

ROOT="${HOME}/Documentos/agentes-v0.1"
UNIT_DIR="${HOME}/.config/systemd/user"
UNIT="${UNIT_DIR}/job-agent.service"
STAMP="$(date +%Y%m%d-%H%M%S)"

cd "$ROOT"
mkdir -p "$UNIT_DIR" logs state

systemctl --user stop job-agent.service 2>/dev/null || true

# Syntax/preflight only: no browser submit and no unit-test marathon.
.venv/bin/python -m py_compile \
  scripts/jobs_loop.py \
  src/agentes/jobs/application_runner.py \
  src/agentes/jobs/custom_known_facts.py \
  src/agentes/jobs/evidence_answerer.py \
  src/agentes/jobs/custom_llm_fallback.py
bash -n scripts/jobs_daemon.sh

if [ -f "$UNIT" ]; then
    cp "$UNIT" "${UNIT}.bak-v0602-${STAMP}"
fi

if [ -d "${UNIT}.d" ]; then
    mv "${UNIT}.d" "${UNIT}.d.bak-v0602-${STAMP}"
fi

cp systemd/job-agent.service "$UNIT"
chmod +x scripts/jobs_daemon.sh scripts/install_v0602_production.sh

systemctl --user daemon-reload
systemctl --user reset-failed job-agent.service 2>/dev/null || true
systemctl --user enable job-agent.service

if [ "${1:-}" = "--start" ]; then
    systemctl --user start job-agent.service
fi

echo "v0.6.2 production hardening instalado."
echo "Estado:"
systemctl --user --no-pager -l status job-agent.service || true
