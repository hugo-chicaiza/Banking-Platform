"""Escribe en Auditoria.Auditoria de SeguridadDB (F-04).

Va en su propia transacción porque también se guardan los intentos fallidos, y en ese
punto la transacción de la operación ya se revirtió. No pasar PIN, PAN, tokens ni
hashes en descripcion.
"""

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import Connection, text
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.api.middleware import ip_cliente
from app.core.config.logs import enmascarar, trace_id_actual
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
    # Roles de WorkOS con que se permitió o negó la operación. Si va None y hay
    # UsuarioID, se toman de Organizacion.Usuarios.RolesWorkOS (actualizado en la
    # misma petición, antes de ejecutar la ruta)
    roles: str | None = None
    # E0-05: agencia, sesión (id del proveedor, nunca su token), canal, correlación (por
    # defecto el traceId de la petición) y cambios (antes/después ya filtrados)
    agencia: str | None = None
    sesion: str | None = None
    canal: str = "API"
    correlacion: str | None = None
    cambios: dict[str, Any] | None = None


# Nunca en la bitácora: datos de tarjeta, PIN, tokens, cookies, contraseñas, invitaciones
_PALABRAS_SENSIBLES = frozenset(
    {
        "pan",
        "pin",
        "cvv",
        "cvc",
        "track",
        "token",
        "cookie",
        "password",
        "contrasena",
        "clave",
        "secret",
        "secreto",
        "invitacion",
        "apikey",
    }
)


def _es_sensible(clave: str) -> bool:
    """Por palabras del nombre (camelCase o snake_case): `pinOffset` sí, `compania` no."""
    separado = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", clave).lower().replace("ñ", "n")
    palabras = set(re.split(r"[^a-z0-9]+", separado))
    return bool(palabras & _PALABRAS_SENSIBLES) or "apikey" in separado.replace("_", "")


_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def texto_seguro(texto: str) -> str:
    """Texto libre para la bitácora (ASVS 16.4.1): caracteres de control escapados, así un
    salto de línea no puede falsificar otro registro; tokens, secretos y PAN enmascarados."""
    return _CONTROL.sub(lambda m: f"\\x{ord(m.group(0)):02x}", enmascarar(texto))


def _filtrar(valor: Any) -> Any:
    if isinstance(valor, dict):
        return {
            str(k): "[filtrado]" if _es_sensible(str(k)) else _filtrar(v)
            for k, v in valor.items()
        }
    if isinstance(valor, (list, tuple)):
        return [_filtrar(v) for v in valor]
    if isinstance(valor, str):
        return texto_seguro(valor)
    return valor


def cambios_json(cambios: dict[str, Any] | None) -> str | None:
    """Antes/después en JSON, sin campos sensibles (se reemplazan por [filtrado])."""
    if not cambios:
        return None
    return json.dumps(_filtrar(cambios), ensure_ascii=False, default=str)


def _insertar(conn: Connection, evento: EventoAuditoria) -> None:
    conn.execute(
        text(
            """
            INSERT INTO Auditoria.Auditoria (
                UsuarioID, NombreAccion, TablaAfectada, IDRegistro, FechaHora,
                DireccionIP, Descripcion, Resultado, RolesWorkOS,
                IdEvento, CodigoEvento, FechaHoraUTC, IdAgencia, IdSesion, Canal,
                IdCorrelacion, TipoObjetivo, IdObjetivo, Cambios
            )
            VALUES (
                :usuario, :accion, :tabla, :id_registro,
                CONVERT(
                    datetime, SYSDATETIMEOFFSET() AT TIME ZONE 'SA Pacific Standard Time'
                ),
                :ip, :descripcion, :resultado,
                COALESCE(
                    :roles,
                    (
                        SELECT u.RolesWorkOS FROM Organizacion.Usuarios AS u
                        WHERE u.UsuarioID = :usuario
                    )
                ),
                NEWID(), :accion, SYSUTCDATETIME(), :agencia, :sesion, :canal,
                :correlacion, :tabla, :id_registro, :cambios
            )
            """
        ),
        {
            "usuario": evento.usuario,
            "accion": evento.accion,
            "tabla": evento.tabla,
            "id_registro": evento.id_registro,
            "ip": evento.ip,
            "descripcion": texto_seguro(evento.descripcion)[:_MAX_DESCRIPCION],
            "resultado": evento.resultado,
            "roles": evento.roles,
            "agencia": (evento.agencia or None)
            if len(evento.agencia or "") <= 3
            else None,
            "sesion": (evento.sesion or None) and evento.sesion[:64],
            "canal": evento.canal[:10],
            "correlacion": (evento.correlacion or trace_id_actual.get())[:64],
            "cambios": cambios_json(evento.cambios),
        },
    )


def _persistir(evento: EventoAuditoria) -> None:
    with get_engine("seguridad").begin() as conn:
        _insertar(conn, evento)


def registrar_en_transaccion(conn: Connection, evento: EventoAuditoria) -> None:
    """Cambios administrativos SQL que deben revertirse si falla su auditoría."""
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
    # Sin consultar la base: solo el id si la petición ya lo había leído
    id_interno = usuario.interno(solo_si_leido=True) if usuario else None
    roles = usuario.roles_texto() if usuario else None
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
        roles=roles,
        agencia=getattr(usuario, "id_agencia", None),
        sesion=getattr(usuario, "id_sesion", None),
        correlacion=trace_id_actual.get(),
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
