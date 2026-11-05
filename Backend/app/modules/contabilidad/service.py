import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import Connection

from app.modules.contabilidad import repository

log = logging.getLogger(__name__)

# Ecuador continental: UTC-5 todo el año (sin horario de verano). El servidor de la
# API puede correr en UTC, pero la hora de corte (19:00) es hora local de Ecuador.
ZONA_ECUADOR = timezone(timedelta(hours=-5))

_FECHA_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# TODO(F-04): reemplazar por ProblemDetails cuando exista core/errors.py.


def _problema(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def ahora_ecuador() -> datetime:
    """Hora actual de Ecuador, sin zona (como la compara la función de la DB)."""
    return datetime.now(ZONA_ECUADOR).replace(tzinfo=None)


def resolver_id_fecha_contable(conn: Connection, fecha_hora: datetime) -> int:
    """IdFechaContable al que pertenece una operación hecha en `fecha_hora` (AC-02).

    Punto de entrada para que otros módulos (caja, ATM, créditos) registren cada
    operación en el día contable correcto sin reimplementar la regla.

    Raises:
        HTTPException 500 CALENDARIO_SIN_FECHA si el calendario no cubre el período.
    """
    id_fecha = repository.id_fecha_contable(conn, fecha_hora)
    if id_fecha is None:
        # Alerta operativa: hay que cargar más fechas en Contabilidad.FechaContable.
        log.error(
            "ALERTA calendario contable sin fechas para %s (DB 51016)", fecha_hora
        )
        raise _problema(
            500,
            "CALENDARIO_SIN_FECHA",
            "El calendario contable no tiene fechas cargadas para este período",
        )
    return id_fecha


def obtener_fecha_contable(conn: Connection, fecha: str) -> dict[str, Any]:
    """CON-01: fila del calendario contable de un día calendario (YYYY-MM-DD).

    Raises:
        HTTPException 400 FECHA_INVALIDA
        HTTPException 404 FECHA_NO_ENCONTRADA
    """
    try:
        if not _FECHA_RE.match(fecha):
            raise ValueError(fecha)
        dia = date.fromisoformat(fecha)
    except ValueError:
        raise _problema(
            400, "FECHA_INVALIDA", "La fecha debe tener el formato YYYY-MM-DD"
        ) from None

    fila = repository.obtener_por_fecha(conn, dia)
    if fila is None:
        raise _problema(
            404, "FECHA_NO_ENCONTRADA", "El calendario contable no tiene esa fecha"
        )
    return fila


def obtener_fecha_contable_actual(conn: Connection) -> dict[str, Any]:
    """CON-02: fecha contable vigente ahora (según la hora de corte).

    Raises:
        HTTPException 500 CALENDARIO_SIN_FECHA
    """
    id_fecha = resolver_id_fecha_contable(conn, ahora_ecuador())
    fila = repository.obtener_por_id(conn, id_fecha)
    if fila is None:
        # La función devolvió un id que no existe: inconsistencia del calendario.
        log.error(
            "ALERTA IdFechaContable %s devuelto por la función no existe", id_fecha
        )
        raise _problema(
            500,
            "CALENDARIO_SIN_FECHA",
            "El calendario contable no tiene fechas cargadas para este período",
        )
    return fila
