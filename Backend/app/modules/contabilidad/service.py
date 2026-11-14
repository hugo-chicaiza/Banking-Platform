import logging
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import Connection

from app.core.api.errors import problema
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
    Una fecha sin zona ya representa hora local de Ecuador; si trae zona, se
    convierte antes de pasarla al datetime2 de SQL Server.

    Raises:
        HTTPException 500 CALENDARIO_SIN_FECHA si el calendario no cubre el período.
    """
    if fecha_hora.utcoffset() is not None:
        fecha_hora = fecha_hora.astimezone(ZONA_ECUADOR).replace(tzinfo=None)
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


def listar_cuentas_contables(
    conn: Connection, q: str | None, imputable: bool | None
) -> list[dict[str, Any]]:
    """CON-03: plan de cuentas con filtro por texto (código o nombre) y por imputable.

    La jerarquía se expresa con idCuentaSuperior; el front arma el árbol. El estado
    de la DB (bit) se publica como "Activo"/"Inactivo".
    """
    return [
        {**fila, "estado": "Activo" if fila["estado"] else "Inactivo"}
        for fila in repository.listar_cuentas_contables(conn, q, imputable)
    ]


def contabilizar_boveda(
    conn: Connection,
    *,
    agencia: str,
    tipo: str,
    naturaleza: str,
    monto: Decimal,
    fecha_contable: int,
    actor: int,
    movimiento: int,
    ahora: datetime,
) -> int:
    """Asiento real de BOV-04/06 en la misma transacción que el efectivo.

    Las cuentas y el tipo de asiento se configuran en PlantillaBoveda por agencia,
    tipo y naturaleza. No se inventa la matriz G-06 ni se confirma efectivo sin ella.
    """
    if not conn.in_transaction():
        raise RuntimeError("La contabilización de bóveda requiere una transacción")
    periodo = repository.periodo_boveda(conn, fecha_contable)
    if periodo is None or periodo["estado"] != "ABIERTO":
        raise problema(
            409, "PERIODO_CONTABLE_NO_ABIERTO", "El período contable no está abierto."
        )
    plantilla = repository.plantilla_boveda(conn, agencia, tipo, naturaleza)
    if plantilla is None or plantilla["estado_tipo"] != "A":
        raise problema(
            409,
            "PLANTILLA_BOVEDA_NO_CONFIGURADA",
            "Falta una plantilla contable activa para esta operación y agencia.",
        )
    cuentas: dict[int, dict[str, Any]] = {}
    for id_cuenta in sorted({plantilla["debito"], plantilla["credito"]}):
        cuenta = repository.cuenta_boveda(conn, id_cuenta)
        if cuenta is None or not cuenta["estado"] or not cuenta["imputable"]:
            raise problema(
                409,
                "CUENTA_CONTABLE_NO_HABILITADA",
                "La plantilla contiene una cuenta inactiva o no imputable.",
            )
        cuentas[id_cuenta] = cuenta
    asiento = repository.crear_asiento_boveda(
        conn,
        {
            "fecha": periodo["fecha"],
            "ahora": ahora,
            "agencia": agencia,
            "tipo_asiento": plantilla["tipo_asiento"],
            "actor": actor,
            "fecha_contable": fecha_contable,
            "concepto": f"Bóveda: {tipo}; movimiento {movimiento}",
        },
    )
    for campo, lado in (("debito", "DEBITO"), ("credito", "CREDITO")):
        cuenta = plantilla[campo]
        repository.linea_boveda(
            conn,
            asiento,
            cuenta,
            agencia,
            monto,
            lado,
            ahora,
            cuentas[cuenta]["naturaleza"],
        )
    repository.confirmar_asiento_boveda(conn, asiento)
    return asiento
