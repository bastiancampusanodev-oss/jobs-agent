#!/usr/bin/env bash
set -uo pipefail

ROOT="${JOB_AGENT_ROOT:-${HOME}/Documentos/agentes-v0.1}"
MODE="${MODE:---auto}"
PREP_LIMIT="${PREP_LIMIT:-${LIMIT:-20}}"
SUBMIT_LIMIT="${SUBMIT_LIMIT:-${LIMIT:-20}}"
INTERVAL="${INTERVAL:-900}"
BUSY_PAUSE="${BUSY_PAUSE:-10}"
SCROLLS="${SCROLLS:-10}"
HEALTH_RETRY="${HEALTH_RETRY:-120}"
ERROR_BACKOFF="${ERROR_BACKOFF:-300}"
JOB_ERROR_RETRY_SECONDS="${JOB_ERROR_RETRY_SECONDS:-900}"
REVIEW_RETRY_SECONDS="${REVIEW_RETRY_SECONDS:-21600}"
HUMAN_REVIEW_RETRY_SECONDS="${HUMAN_REVIEW_RETRY_SECONDS:-21600}"
ANALYZED_RETRY_SECONDS="${ANALYZED_RETRY_SECONDS:-900}"
CTA_MISSING_RETRY_SECONDS="${CTA_MISSING_RETRY_SECONDS:-21600}"
MAX_CONSECUTIVE_FAILURES="${MAX_CONSECUTIVE_FAILURES:-5}"
BRAVE_CDP_URL="${BRAVE_CDP_URL:-http://127.0.0.1:9222/json/version}"
OLLAMA_TAGS_URL="${OLLAMA_TAGS_URL:-http://127.0.0.1:11434/api/tags}"
LOCK_FILE="${LOCK_FILE:-${ROOT}/state/job-agent.lock}"

# systemd user services can inherit a much smaller PATH than an interactive shell.
# Keep runtime dependencies deterministic and include the venv explicitly.
export PATH="$ROOT/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/snap/bin:${PATH:-}"

mkdir -p "$ROOT/logs" "$ROOT/state"

# One autonomous agent per profile/DB. A manual second daemon exits cleanly.
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "[$(date -Is)] Otra instancia del Job Agent ya está activa. Salgo."
    exit 0
fi

case "$MODE" in
    --auto|--submit)
        if [ "${AGENT_SUBMIT_ARMED:-}" != "YES" ]; then
            echo "SUBMIT bloqueado: falta AGENT_SUBMIT_ARMED=YES" >&2
            exit 64
        fi
        ;;
    --dry-run)
        ;;
    *)
        echo "MODE inválido: $MODE (usa --auto, --submit o --dry-run)" >&2
        exit 64
        ;;
esac

cd "$ROOT" || exit 70
if [ ! -r .venv/bin/activate ]; then
    echo "No existe .venv/bin/activate en $ROOT" >&2
    exit 70
fi
# shellcheck disable=SC1091
source .venv/bin/activate

for dependency in flock curl python; do
    if ! command -v "$dependency" >/dev/null 2>&1; then
        echo "Dependencia requerida no encontrada: $dependency" >&2
        exit 70
    fi
done

for n in PREP_LIMIT SUBMIT_LIMIT INTERVAL BUSY_PAUSE SCROLLS HEALTH_RETRY ERROR_BACKOFF \
         JOB_ERROR_RETRY_SECONDS REVIEW_RETRY_SECONDS HUMAN_REVIEW_RETRY_SECONDS \
         ANALYZED_RETRY_SECONDS CTA_MISSING_RETRY_SECONDS MAX_CONSECUTIVE_FAILURES; do
    value="${!n}"
    if ! [[ "$value" =~ ^[0-9]+$ ]]; then
        echo "$n debe ser entero >= 0; recibido: $value" >&2
        exit 64
    fi
done

if [ "$PREP_LIMIT" -lt 1 ] || [ "$SUBMIT_LIMIT" -lt 1 ]; then
    echo "PREP_LIMIT y SUBMIT_LIMIT deben ser >= 1" >&2
    exit 64
fi

log_config() {
    echo "=== JOB AGENT v0.6.11.13b PRODUCTION ==="
    echo "MODE=$MODE"
    echo "PREP_LIMIT=$PREP_LIMIT SUBMIT_LIMIT=$SUBMIT_LIMIT"
    echo "INTERVAL=$INTERVAL BUSY_PAUSE=$BUSY_PAUSE SCROLLS=$SCROLLS"
    echo "MAX_CONSECUTIVE_FAILURES=$MAX_CONSECUTIVE_FAILURES"
    echo "JOB_ERROR_RETRY_SECONDS=$JOB_ERROR_RETRY_SECONDS"
    echo "REVIEW_RETRY_SECONDS=$REVIEW_RETRY_SECONDS"
    echo "HUMAN_REVIEW_RETRY_SECONDS=$HUMAN_REVIEW_RETRY_SECONDS"
    echo "ANALYZED_RETRY_SECONDS=$ANALYZED_RETRY_SECONDS"
    echo "CTA_MISSING_RETRY_SECONDS=$CTA_MISSING_RETRY_SECONDS"
    echo "ROOT=$ROOT"
}

brave_ok() {
    curl -fsS --max-time 5 "$BRAVE_CDP_URL" >/dev/null 2>&1
}

ollama_ok() {
    curl -fsS --max-time 5 "$OLLAMA_TAGS_URL" >/dev/null 2>&1
}

ensure_brave() {
    if brave_ok; then
        return 0
    fi

    echo "[$(date -Is)] Brave/CDP OFFLINE → iniciando perfil del agente..."
    nohup ./scripts/launch_brave_debug.sh > logs/brave-agent.log 2>&1 &

    for _ in 1 2 3 4 5; do
        sleep 3
        if brave_ok; then
            echo "[$(date -Is)] Brave/CDP OK."
            return 0
        fi
    done

    echo "[$(date -Is)] Brave/CDP sigue OFFLINE."
    return 1
}

ensure_ollama() {
    if ollama_ok; then
        return 0
    fi

    echo "[$(date -Is)] Ollama OFFLINE → intentando iniciar ollama serve..."
    if command -v ollama >/dev/null 2>&1; then
        nohup ollama serve > logs/ollama-agent.log 2>&1 &
    else
        echo "[$(date -Is)] Binario ollama no encontrado."
        return 1
    fi

    for _ in 1 2 3 4 5; do
        sleep 2
        if ollama_ok; then
            echo "[$(date -Is)] Ollama OK."
            return 0
        fi
    done

    echo "[$(date -Is)] Ollama sigue OFFLINE."
    return 1
}

notify_agent() {
    local message="$1"
    if command -v notify-send >/dev/null 2>&1; then
        notify-send "Job Agent" "$message" >/dev/null 2>&1 || true
    fi
}

count_status_since() {
    local since="$1"
    shift

    # Use Python's stdlib sqlite3 instead of the external sqlite3 CLI.
    # This removes a systemd PATH dependency while keeping the query read-only.
    python - "$since" "$@" <<'PY'
import sqlite3
import sys

since = sys.argv[1]
statuses = sys.argv[2:]
if not statuses:
    print(0)
    raise SystemExit(0)

placeholders = ",".join("?" for _ in statuses)
query = f"""
    SELECT COUNT(*)
    FROM job_loop
    WHERE status IN ({placeholders})
      AND julianday(updated_at) >= julianday(?)
"""

try:
    con = sqlite3.connect("state/job_loop.db")
    row = con.execute(query, (*statuses, since)).fetchone()
    print(int(row[0] if row else 0))
except Exception as exc:
    print(f"count_status_since error: {exc}", file=sys.stderr)
    print(0)
finally:
    try:
        con.close()
    except Exception:
        pass
PY
}

count_updates_since() {
    local since="$1"
    python - "$since" <<'PY'
import sqlite3
import sys

since = sys.argv[1]
try:
    con = sqlite3.connect("state/job_loop.db")
    row = con.execute(
        "SELECT COUNT(*) FROM job_loop WHERE julianday(updated_at) >= julianday(?)",
        (since,),
    ).fetchone()
    print(int(row[0] if row else 0))
except Exception as exc:
    print(f"count_updates_since error: {exc}", file=sys.stderr)
    print(0)
finally:
    try:
        con.close()
    except Exception:
        pass
PY
}

count_status_now() {
    python - "$@" <<'PY'
import sqlite3
import sys

statuses = sys.argv[1:]
if not statuses:
    print(0)
    raise SystemExit(0)

placeholders = ",".join("?" for _ in statuses)
try:
    con = sqlite3.connect("state/job_loop.db")
    row = con.execute(
        f"SELECT COUNT(*) FROM job_loop WHERE status IN ({placeholders})",
        tuple(statuses),
    ).fetchone()
    print(int(row[0] if row else 0))
except Exception as exc:
    print(f"count_status_now error: {exc}", file=sys.stderr)
    print(0)
finally:
    try:
        con.close()
    except Exception:
        pass
PY
}

count_requeue_now() {
    python - <<'PY'
import sqlite3
import sys
try:
    con = sqlite3.connect("state/job_loop.db")
    row = con.execute(
        "SELECT COUNT(*) FROM job_loop WHERE status LIKE 'REQUEUE_%'"
    ).fetchone()
    print(int(row[0] if row else 0))
except Exception as exc:
    print(f"count_requeue_now error: {exc}", file=sys.stderr)
    print(0)
finally:
    try:
        con.close()
    except Exception:
        pass
PY
}


count_error_like_since() {
    local since="$1"
    local pattern="$2"

    python - "$since" "$pattern" <<'PY'
import sqlite3
import sys

since = sys.argv[1]
pattern = sys.argv[2]

try:
    con = sqlite3.connect("state/job_loop.db")
    row = con.execute(
        """
        SELECT COUNT(*)
        FROM job_loop
        WHERE status = 'ERROR'
          AND last_error LIKE ?
          AND julianday(updated_at) >= julianday(?)
        """,
        (pattern, since),
    ).fetchone()

    print(int(row[0] if row else 0))
except Exception as exc:
    print(
        f"count_error_like_since error: {exc}",
        file=sys.stderr,
    )
    print(0)
finally:
    try:
        con.close()
    except Exception:
        pass
PY
}


count_retryable_errors_now() {
    python - "$JOB_ERROR_RETRY_SECONDS" <<'PY'
import sqlite3
import sys

backoff = int(sys.argv[1])

try:
    con = sqlite3.connect("state/job_loop.db")
    row = con.execute(
        """
        SELECT COUNT(*)
        FROM job_loop
        WHERE status = 'ERROR'
          AND julianday(updated_at)
              <= julianday(
                    'now',
                    '-' || ? || ' seconds'
                 )
        """,
        (backoff,),
    ).fetchone()

    print(int(row[0] if row else 0))
except Exception as exc:
    print(
        f"count_retryable_errors_now error: {exc}",
        file=sys.stderr,
    )
    print(0)
finally:
    try:
        con.close()
    except Exception:
        pass
PY
}


ollama_inference_ok() {
    python - <<'PY'
import json
import os
import sys
import urllib.request

models = []
for model in (
    os.getenv("AGENT_ANALYSIS_MODEL", "llama3.2:1b"),
    os.getenv("AGENT_MODEL", "llama3.2:3b"),
):
    model = str(model or "").strip()
    if model and model not in models:
        models.append(model)

url = os.getenv(
    "OLLAMA_CHAT_URL",
    "http://127.0.0.1:11434/api/chat",
)

for model in models:
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": "Reply only with OK",
            }
        ],
        "stream": False,
        "keep_alive": "5m",
        "options": {
            "num_ctx": 256,
            "num_predict": 3,
            "temperature": 0,
        },
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            req,
            timeout=45,
        ) as response:
            raw = json.loads(
                response.read().decode("utf-8")
            )

        content = (
            raw.get("message", {})
            .get("content", "")
            .strip()
        )

        if not content:
            raise RuntimeError("respuesta vacía")

        print(
            f"Ollama inference health OK: "
            f"model={model} response={content[:40]!r}"
        )

    except Exception as exc:
        print(
            f"Ollama inference health FAIL: "
            f"model={model}: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(1)
PY
}



recover_ollama() {
    echo "[$(date -Is)] Recuperando Ollama/modelo..."

    if command -v ollama >/dev/null 2>&1; then
        ollama stop "${AGENT_MODEL:-llama3.2:3b}" \
            >/dev/null 2>&1 || true
    fi

    sleep 3
}


recover_brave() {
    echo "[$(date -Is)] Recuperando Brave/CDP..."

    pkill -TERM -f \
        'Brave-Browser-Agent' \
        >/dev/null 2>&1 || true

    sleep 3

    ensure_brave
}


run_lane() {
    local lane="$1"
    local limit="$2"
    local rc

    echo "[$(date -Is)] === ${lane} limit=${limit} ==="

    if [ "$lane" = "DRY_RUN" ]; then
        python scripts/jobs_loop.py \
            --dry-run \
            --limit "$limit" \
            --scrolls "$SCROLLS"
        rc=$?
    else
        python scripts/jobs_loop.py \
            --submit \
            --limit "$limit" \
            --scrolls "$SCROLLS"
        rc=$?
    fi

    return "$rc"
}

handle_rc() {
    local lane="$1"
    local rc="$2"

    if [ "$rc" -eq 0 ]; then
        return 0
    fi

    if [ "$rc" -eq 42 ]; then
        echo "[$(date -Is)] AUTH_REQUIRED en ${lane}. Deteniendo producción."
        notify_agent "Get on Board requiere login/2FA. Producción detenida."
        exit 42
    fi

    if [ "$rc" -eq 64 ]; then
        echo "[$(date -Is)] Guardrail/configuración inválida en ${lane}. Deteniendo."
        exit 64
    fi

    return "$rc"
}


# v0.6.4 override: recover both the fast triage model and
# the larger complex-question fallback model.
recover_ollama() {
    echo "[$(date -Is)] Recuperando Ollama/modelos v0.6.4..."

    local analysis_model="${AGENT_ANALYSIS_MODEL:-llama3.2:1b}"
    local fallback_model="${AGENT_MODEL:-llama3.2:3b}"

    if command -v ollama >/dev/null 2>&1; then
        ollama stop "$analysis_model" >/dev/null 2>&1 || true

        if [ "$fallback_model" != "$analysis_model" ]; then
            ollama stop "$fallback_model" >/dev/null 2>&1 || true
        fi
    fi

    sleep 3
}

log_config

consecutive_failures=0
llm_verified=0

while true; do
    cycle_started="$(date -u +%Y-%m-%dT%H:%M:%S+00:00)"

    echo
    echo "[$(date -Is)] ===== CICLO AUTOMÁTICO v0.6.11.13b ====="

    # ------------------------------------------------------------
    # HEALTH: OLLAMA PROCESS
    # ------------------------------------------------------------
    if ! ensure_ollama; then
        consecutive_failures=$((consecutive_failures + 1))

        echo \
            "[$(date -Is)] Health Ollama falló " \
            "(${consecutive_failures}/${MAX_CONSECUTIVE_FAILURES})."

        if [ "$consecutive_failures" -ge "$MAX_CONSECUTIVE_FAILURES" ]; then
            notify_agent \
                "Ollama no responde. Job Agent detenido por circuit breaker."
            exit 75
        fi

        sleep "$HEALTH_RETRY"
        continue
    fi

    # /api/tags is not enough. Verify one real tiny inference at startup
    # and again after any LLM failure.
    if [ "$llm_verified" -eq 0 ]; then
        echo "[$(date -Is)] Verificando inferencia Ollama real..."

        if ! ollama_inference_ok; then
            consecutive_failures=$((consecutive_failures + 1))

            echo \
                "[$(date -Is)] Inferencia Ollama no saludable " \
                "(${consecutive_failures}/${MAX_CONSECUTIVE_FAILURES})."

            recover_ollama

            if [ "$consecutive_failures" -ge "$MAX_CONSECUTIVE_FAILURES" ]; then
                notify_agent \
                    "Inferencia Ollama falló repetidamente."
                exit 75
            fi

            sleep "$HEALTH_RETRY"
            continue
        fi

        llm_verified=1
    fi

    # ------------------------------------------------------------
    # HEALTH: BRAVE
    # ------------------------------------------------------------
    if ! ensure_brave; then
        consecutive_failures=$((consecutive_failures + 1))

        echo \
            "[$(date -Is)] Health Brave falló " \
            "(${consecutive_failures}/${MAX_CONSECUTIVE_FAILURES})."

        if [ "$consecutive_failures" -ge "$MAX_CONSECUTIVE_FAILURES" ]; then
            notify_agent \
                "Brave/CDP no responde. Job Agent detenido."
            exit 75
        fi

        sleep "$HEALTH_RETRY"
        continue
    fi

    cycle_failed=0

    # ------------------------------------------------------------
    # PRIORITY 1: DRAIN READY BEFORE MORE DISCOVERY
    # ------------------------------------------------------------
    ready_before="$(count_status_now DRY_RUN_READY)"

    if { [ "$MODE" = "--auto" ] && [ "${ready_before:-0}" -gt 0 ]; } || [ "$MODE" = "--submit" ]; then

        echo \
            "[$(date -Is)] READY prioritario: " \
            "${ready_before:-0}"

        if ! ensure_brave; then
            cycle_failed=1
        else
            run_lane "SUBMIT" "$SUBMIT_LIMIT"
            rc=$?

            if ! handle_rc "SUBMIT" "$rc"; then
                cycle_failed=1
                echo "[$(date -Is)] SUBMIT inicial rc=$rc"
            fi
        fi
    fi

    # ------------------------------------------------------------
    # PRIORITY 2: PREP / REPAIR / DISCOVERY
    # ------------------------------------------------------------
    if [ "$MODE" = "--auto" ] || [ "$MODE" = "--dry-run" ]; then

        if ! ensure_brave; then
            cycle_failed=1
        else
            run_lane "DRY_RUN" "$PREP_LIMIT"
            rc=$?

            if ! handle_rc "DRY_RUN" "$rc"; then
                cycle_failed=1
                echo "[$(date -Is)] DRY_RUN rc=$rc"
            fi
        fi
    fi

    # ------------------------------------------------------------
    # PRIORITY 3: IMMEDIATE SUBMIT OF NEW READY
    # ------------------------------------------------------------
    ready_after="$(count_status_now DRY_RUN_READY)"

    if [ "$MODE" = "--auto" ] && [ "${ready_after:-0}" -gt 0 ]; then

        echo \
            "[$(date -Is)] Nuevos READY → SUBMIT inmediato: " \
            "${ready_after:-0}"

        if ! ensure_brave; then
            cycle_failed=1
        else
            run_lane "SUBMIT" "$SUBMIT_LIMIT"
            rc=$?

            if ! handle_rc "SUBMIT" "$rc"; then
                cycle_failed=1
                echo "[$(date -Is)] SUBMIT posterior rc=$rc"
            fi
        fi
    fi

    # ------------------------------------------------------------
    # IRREVERSIBLE GUARDRAIL
    # ------------------------------------------------------------
    fresh_unknown="$(
        count_status_since \
            "$cycle_started" \
            SUBMIT_UNKNOWN \
            CONFIRMATION_REQUIRED
    )"

    if [ "${fresh_unknown:-0}" -gt 0 ]; then
        echo "[$(date -Is)] Estado irreversible ambiguo detectado."
        echo "[$(date -Is)] Oferta(s) en CUARENTENA; producción continúa."
        notify_agent "SUBMIT_UNKNOWN/CONFIRMATION_REQUIRED en cuarentena. Job Agent continúa con otras ofertas."

        # Never re-click ambiguous irreversible submissions.
        #
        # jobs_loop.py persists SUBMIT_UNKNOWN or
        # CONFIRMATION_REQUIRED before returning here and
        # treats those statuses as terminal quarantine.
        #
        # Therefore we warn, but DO NOT kill the factory.
    fi

    # ------------------------------------------------------------
    # INFRASTRUCTURE CIRCUIT BREAKERS
    # ------------------------------------------------------------
    fresh_llm="$(
        count_error_like_since \
            "$cycle_started" \
            'TRANSIENT_LLM:%'
    )"

    fresh_browser="$(
        count_error_like_since \
            "$cycle_started" \
            'TRANSIENT_BROWSER:%'
    )"

    if [ "${fresh_llm:-0}" -gt 0 ]; then
        echo \
            "[$(date -Is)] LLM transient detectado: " \
            "${fresh_llm}. Recuperando antes de continuar."

        llm_verified=0
        recover_ollama

        sleep "$HEALTH_RETRY"
        continue
    fi

    if [ "${fresh_browser:-0}" -gt 0 ]; then
        echo \
            "[$(date -Is)] Browser transient detectado: " \
            "${fresh_browser}. Recuperando antes de continuar."

        if ! recover_brave; then
            cycle_failed=1
        fi

        sleep "$HEALTH_RETRY"
        continue
    fi

    # ------------------------------------------------------------
    # ORDINARY PROCESS FAILURE
    # ------------------------------------------------------------
    if [ "$cycle_failed" -eq 1 ]; then
        consecutive_failures=$((consecutive_failures + 1))

        echo \
            "[$(date -Is)] Fallo de ciclo " \
            "(${consecutive_failures}/${MAX_CONSECUTIVE_FAILURES})."

        if [ "$consecutive_failures" -ge "$MAX_CONSECUTIVE_FAILURES" ]; then
            notify_agent \
                "Demasiados fallos consecutivos. Producción detenida."
            exit 75
        fi

        sleep "$ERROR_BACKOFF"
        continue
    fi

    consecutive_failures=0

    # ------------------------------------------------------------
    # REAL PROGRESS
    # ------------------------------------------------------------
    #
    # ERROR is deliberately NOT included. An ERROR must never be
    # mistaken for productive work again.
    productive_updates="$(
        count_status_since \
            "$cycle_started" \
            ANALYZED \
            DRY_RUN_READY \
            SUBMITTED \
            SKIP \
            ALREADY_APPLIED \
            HUMAN_REVIEW \
            REVIEW
    )"

    ready_now="$(count_status_now DRY_RUN_READY)"
    requeue_now="$(count_requeue_now)"
    retryable_errors="$(count_retryable_errors_now)"

    echo \
        "[$(date -Is)] Progreso REAL:" \
        "productive=${productive_updates}" \
        "ready=${ready_now}" \
        "requeue=${requeue_now}" \
        "retryable_errors=${retryable_errors}"

    if \
        [ "${productive_updates:-0}" -gt 0 ] \
        || [ "${ready_now:-0}" -gt 0 ] \
        || [ "${requeue_now:-0}" -gt 0 ] \
        || [ "${retryable_errors:-0}" -gt 0 ]; then

        echo \
            "[$(date -Is)] Trabajo accionable. " \
            "Siguiente ciclo en ${BUSY_PAUSE}s."

        sleep "$BUSY_PAUSE"
        continue
    fi

    echo \
        "[$(date -Is)] Sin trabajo accionable. " \
        "Discovery poll en ${INTERVAL}s."

    sleep "$INTERVAL"
done
