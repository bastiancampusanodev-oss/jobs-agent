# Job Agent v0.5.29 — patch de cierre preproducción

## Cambios

- Resolver canónico de step Get on Board: hidden `job_application[step]` -> `?step=` URL.
- `detect_stage()` prioriza ese step y reconoce `experience`, `basic` y `custom`.
- `learn_form_constraints()` usa resolver canónico y fallback del stage del agente.
- REPAIR MODE recupera y persiste automáticamente `repair_step` si una fila histórica quedó con `{}`.
- Diagnóstico read-only previo a reparar: URL, GOB STEP y AGENT STAGE.
- Nuevo `--url` para procesar una oferta exacta sin backlog/discovery.
- Desempate estable de cola: `score DESC`, `updated_at ASC`, `url ASC`.
- `jobs_daemon.sh` falla cerrado en `--submit` si falta `AGENT_SUBMIT_ARMED=YES`.
- No se cambia la semántica irreversible: un solo click final, sin retry.

## Archivos

- `src/agentes/jobs/gob_stage.py` (nuevo)
- `src/agentes/jobs/application_runner.py`
- `scripts/jobs_loop.py`
- `scripts/jobs_daemon.sh`
- `tests/test_gob_stage.py` (nuevo)

## Validación hecha en sandbox

- `python -m py_compile`: PASS
- tests originales + regresión: `8 passed`
- `bash -n scripts/jobs_daemon.sh`: PASS
- daemon con `MODE=--submit` sin arm: sale con código `64` antes de iniciar el loop.

## Aplicación segura

Con el servicio detenido:

```bash
cd ~/Documentos/agentes-v0.1
source .venv/bin/activate
systemctl --user stop job-agent.service

stamp=$(date +%Y%m%d-%H%M%S)
cp scripts/jobs_loop.py "scripts/jobs_loop.py.bak-v0529-$stamp"
cp scripts/jobs_daemon.sh "scripts/jobs_daemon.sh.bak-v0529-$stamp"
cp src/agentes/jobs/application_runner.py \
  "src/agentes/jobs/application_runner.py.bak-v0529-$stamp"

unzip -o ~/Descargas/agentes-v0.1-v0529-safe-patch.zip -d .

python -m py_compile \
  src/agentes/jobs/gob_stage.py \
  src/agentes/jobs/application_runner.py \
  scripts/jobs_loop.py

pytest -q
bash -n scripts/jobs_daemon.sh
```

## Primera prueba: SRE, sólo DRY RUN

No armar submit todavía.

```bash
cd ~/Documentos/agentes-v0.1
source .venv/bin/activate
systemctl --user stop job-agent.service

python scripts/jobs_loop.py \
  --dry-run \
  --limit 1 \
  --url 'https://www.getonbrd.com/jobs/sysadmin-devops-qa/site-reliability-engineer-sre-bc-tecnologia-remote'
```

Buscar en la salida:

```text
REPAIR DIAGNÓSTICO
GOB STEP=...
AGENT STAGE=...
repair_step recuperado automáticamente: ...
```

Si Get on Board conserva el rechazo en CUSTOM, lo esperado es `custom` y el ciclo debe terminar nuevamente en `DRY_RUN_READY` sin tocar SQLite manualmente.

## Verificación DB después del dry-run

```bash
sqlite3 -header -column state/job_loop.db "
SELECT
    status,
    score,
    cv_id,
    json_extract(decision_json, '$.salary_usd_monthly') AS salary,
    json_extract(decision_json, '$.form_constraints.repair_step') AS repair_step
FROM job_loop
WHERE url LIKE '%site-reliability-engineer-sre-bc%';
"
```

No ejecutar un submit real hasta revisar la salida de esta prueba.
