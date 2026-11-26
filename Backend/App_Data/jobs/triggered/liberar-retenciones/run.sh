#!/bin/bash
set -euo pipefail

APP_ROOT="${TAREAS_APP_ROOT:-/home/site/wwwroot}"
PYTHON="${TAREAS_PYTHON:-${APP_ROOT}/antenv/bin/python}"
if [[ ! -x "$PYTHON" || ! -f "$APP_ROOT/app/core/tareas/__main__.py" ]]; then
    printf '%s\n' 'TAREA_SIN_EJECUTAR reason=RUNTIME_NOT_CONFIGURED' >&2
    exit 1
fi
export PYTHONPATH="${APP_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
cd -- "$APP_ROOT"
exec "$PYTHON" -m app.core.tareas ejecutar CTA_LIBERAR_RETENCIONES
