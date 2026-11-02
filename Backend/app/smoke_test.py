"""Endpoint temporal para comprobar el despliegue en Azure.

Para quitarlo: borrar este archivo y las 2 líneas SMOKE-TEST de app/main.py.
"""

import logging
from typing import Literal

import pyodbc
from fastapi import APIRouter

from app.core.config import get_settings

router = APIRouter(prefix="/smoke-test", tags=["smoke-test"])
logger = logging.getLogger(__name__)


def _db_ok(db: Literal["cooperativa", "seguridad"]) -> bool:
    settings = get_settings()
    try:
        with pyodbc.connect(
            settings.odbc_connection_string(db),
            timeout=settings.db_connection_timeout,
        ) as conn:
            conn.execute("SELECT 1").fetchone()
        return True
    except pyodbc.Error:
        # El detalle va al log; la respuesta solo dice si conectó
        logger.exception("smoke-test: fallo de conexión a %s", db)
        return False


@router.get("")
def smoke_test() -> dict[str, object]:
    settings = get_settings()
    return {
        "app": "ok",
        "env": settings.app_env,
        "odbc_driver": settings.db_driver in pyodbc.drivers(),
        "cooperativa_db": _db_ok("cooperativa"),
        "seguridad_db": _db_ok("seguridad"),
    }
