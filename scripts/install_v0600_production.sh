#!/usr/bin/env bash
set -euo pipefail

ROOT="${HOME}/Documentos/agentes-v0.1"
UNIT_DIR="${HOME}/.config/systemd/user"
UNIT="${UNIT_DIR}/job-agent.service"
STAMP="$(date +%Y%m%d-%H%M%S)"

cd "$ROOT"
mkdir -p "$UNIT_DIR" logs state

systemctl --user stop job-agent.service 2>/dev/null || true

if [ -f "$UNIT" ]; then
    cp "$UNIT" "${UNIT}.bak-v0600-${STAMP}"
fi

if [ -d "${UNIT}.d" ]; then
    mv "${UNIT}.d" "${UNIT}.d.bak-v0600-${STAMP}"
fi

cp systemd/job-agent.service "$UNIT"
chmod +x scripts/jobs_daemon.sh

systemctl --user daemon-reload
systemctl --user reset-failed job-agent.service 2>/dev/null || true
systemctl --user enable job-agent.service

if [ "${1:-}" = "--start" ]; then
    systemctl --user start job-agent.service
fi

echo "v0.6.0 production unit instalada."
echo "Estado:"
systemctl --user --no-pager status job-agent.service || true
