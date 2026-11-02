"""Escribe en Auditoria.Auditoria de SeguridadDB (F-04).

Va en su propia transacción porque también se guardan los intentos fallidos, y en ese
punto la transacción de la operación ya se revirtió. No pasar PIN, PAN, tokens ni
hashes en descripcion.
"""

import logging
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import Connection, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.db import get_engine

logger = logging.getLogger(__name__)

Resultado = Literal["Exitoso", "Fallido"]

_MAX_DESCRIPCION = 500


@dataclass(frozen=True)
class EventoAuditoria:
    accion: str
    tabla: str
    id_registro: str | None
    resultado: Resultado
    usuario: int | None
    ip: str | None
    descripcion: str


def _insertar(conn: Connection, evento: EventoAuditoria) -> None:
    conn.execute(
        text(
            """
            INSERT INTO Auditoria.Auditoria (
                UsuarioID, NombreAccion, TablaAfectada, IDRegistro, FechaHora,
                DireccionIP, Descripcion, Resultado
            )
            VALUES (
                :usuario, :accion, :tabla, :id_registro,
                CONVERT(
                    datetime, SYSDATETIMEOFFSET() AT TIME ZONE 'SA Pacific Standard Time'
                ),
                :ip, :descripcion, :resultado
            )
            """
        ),
        {
            "usuario": evento.usuario,
            "accion": evento.accion,
            "tabla": evento.tabla,
            "id_registro": evento.id_registro,
            "ip": evento.ip,
            "descripcion": evento.descripcion[:_MAX_DESCRIPCION],
            "resultado": evento.resultado,
        },
    )


def _persistir(evento: EventoAuditoria) -> None:
    with get_engine("seguridad").begin() as conn:
        _insertar(conn, evento)


def registrar(evento: EventoAuditoria) -> None:
    """Si falla, solo queda en el log: la operación auditada ya terminó y devolver un
    error haría creer al usuario que no se hizo.
    """
    try:
        _persistir(evento)
    except SQLAlchemyError as exc:
        # Solo el tipo: str(exc) trae los parámetros de la consulta
        logger.error(
            "auditoria: no se pudo registrar accion=%s tabla=%s resultado=%s tipo=%s",
            evento.accion,
            evento.tabla,
            evento.resultado,
            type(exc).__name__,
        )
