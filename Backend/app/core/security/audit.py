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
from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.api.middleware import ip_cliente
from app.core.config.logs import trace_id_actual
from app.core.config.settings import get_settings
from app.core.database.db import get_engine

logger = logging.getLogger(__name__)

Resultado = Literal["Exitoso", "Fallido"]

_MAX_DESCRIPCION = 500
_ESTADOS_DENEGADOS = {401, 403}


@dataclass(frozen=True)
class EventoAuditoria:
    accion: str
    tabla: str | None
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


def evento_acceso_denegado(scope: Scope, status: int) -> EventoAuditoria:
    """Sin query string ni cuerpo: pueden traer datos personales. El traceId une el
    registro con la línea del log que tiene el code del rechazo.
    """
    usuario = (scope.get("state") or {}).get("usuario")
    id_workos = getattr(usuario, "id_usuario", None)
    id_interno = (
        get_settings().workos_audit_user_ids.get(id_workos) if id_workos else None
    )
    descripcion = (
        f"{status} {scope['method']} {scope['path']} trace={trace_id_actual.get()}"
    )
    if id_workos and id_interno is None:
        descripcion += f" usuario={id_workos}"
    return EventoAuditoria(
        accion="ACCESO_DENEGADO",
        tabla=None,
        id_registro=None,
        resultado="Fallido",
        usuario=id_interno,
        ip=ip_cliente(scope),
        descripcion=descripcion,
    )


class AccesoDenegadoMiddleware:
    """ASVS 16.3.2: registra en Auditoria.Auditoria cada 401 y 403 de la API.

    Va como middleware para cubrir todos los routers, tengan o no ProblemDetailsRoute.
    Se escribe después de enviar la respuesta, en un hilo, para no demorarla.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            await self.app(scope, receive, send)
            return
        status: int | None = None

        async def enviar(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        await self.app(scope, receive, enviar)
        if status in _ESTADOS_DENEGADOS:
            await run_in_threadpool(registrar, evento_acceso_denegado(scope, status))
