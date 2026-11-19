#!/bin/bash
set -euo pipefail

# E0-06: corre por el ejecutor de tareas (bloqueo + registro en Sistema.TareaEjecucion).
# No instalar dependencias ni invocar HTTP. Usar el runtime ya desplegado.
APP_ROOT="${ATM_PIN_RECOVERY_APP_ROOT:-/home/site/wwwroot}"
PYTHON="${ATM_PIN_RECOVERY_PYTHON:-${APP_ROOT}/antenv/bin/python}"
if [[ ! -x "$PYTHON" || ! -f "$APP_ROOT/app/core/tareas/__main__.py" ]]; then
    printf '%s\n' 'ATM06_RECOVERY_ALERT reason=RUNTIME_NOT_CONFIGURED' >&2
    exit 1
fi
export PYTHONPATH="${APP_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
cd -- "$APP_ROOT"
exec "$PYTHON" -m app.core.tareas ejecutar ATM06_RECUPERACION
