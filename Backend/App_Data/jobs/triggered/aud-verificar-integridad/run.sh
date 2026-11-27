#!/bin/bash
set -euo pipefail

APP_ROOT="${TAREAS_APP_ROOT:-/home/site/wwwroot}"
PYTHON="${TAREAS_PYTHON:-${APP_ROOT}/antenv/bin/python}"
export PYTHONPATH="${APP_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
cd -- "$APP_ROOT"
exec "$PYTHON" -m app.core.tareas ejecutar AUD_VERIFICAR_INTEGRIDAD
