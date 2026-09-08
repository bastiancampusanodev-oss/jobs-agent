#!/usr/bin/env bash
set -euo pipefail

PORT="${BRAVE_DEBUG_PORT:-9222}"
PROFILE_DIR="${BRAVE_AGENT_PROFILE:-$HOME/.config/BraveSoftware/Brave-Browser-Agent}"

# ----------------------------------------------------------
# Recuperar entorno gráfico incluso cuando nos lanza systemd.
# ----------------------------------------------------------

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=${XDG_RUNTIME_DIR}/bus}"

# Preferimos Wayland si existe.
if [[ -z "${WAYLAND_DISPLAY:-}" ]]; then
    for socket in "${XDG_RUNTIME_DIR}"/wayland-*; do
        if [[ -S "$socket" ]]; then
            export WAYLAND_DISPLAY="$(basename "$socket")"
            break
        fi
    done
fi

# Fallback X11.
if [[ -z "${DISPLAY:-}" ]]; then
    for socket in /tmp/.X11-unix/X*; do
        if [[ -S "$socket" ]]; then
            n="${socket##*/X}"
            export DISPLAY=":${n}"
            break
        fi
    done
fi

if command -v brave-browser >/dev/null 2>&1; then
    BRAVE=brave-browser
elif command -v brave >/dev/null 2>&1; then
    BRAVE=brave
else
    echo "Brave executable not found." >&2
    exit 1
fi

ARGS=(
    "--remote-debugging-port=${PORT}"
    "--user-data-dir=${PROFILE_DIR}"
    "--no-first-run"
    "--no-default-browser-check"
    "--disable-session-crashed-bubble"
)

if [[ -n "${WAYLAND_DISPLAY:-}" ]]; then
    ARGS+=("--ozone-platform=wayland")
fi

echo "Launching Brave Agent"
echo "PORT=$PORT"
echo "PROFILE=$PROFILE_DIR"
echo "DISPLAY=${DISPLAY:-<none>}"
echo "WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-<none>}"
echo "XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR"

START_URL="${BRAVE_START_URL:-https://www.getonbrd.com/myjobs}"

echo "START_URL=$START_URL"

exec "$BRAVE" "${ARGS[@]}" --new-window "$START_URL"
