"""Datos del operador que necesitan Caja y Transacciones, y su auditoría.

Caja.JornadasCaja.IdUsuario, CajerosAsignadosAgencia.IdUsuario, CuadreCaja.IdAutorizadoPor
y Transaccion.CreadoPor son `int`. WorkOS entrega `user_01...`: ese texto no se convierte
a número ni se adivina.

El vínculo es Organizacion.Usuarios.KeyUsuario = id del usuario en WorkOS
(Usuario.interno()). Sin vínculo, o si el usuario no está Activo, las rutas
que necesitan el id interno responden 403 USUARIO_INTERNO_NO_VINCULADO: fallan cerradas.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.api.errors import problema
from app.core.security import audit
from app.core.security.auth import Usuario, UsuarioActual


def resolver_id_interno(usuario: UsuarioActual) -> int | None:
    """Id interno (int) del usuario autenticado, vinculado por KeyUsuario."""
    return usuario.interno()


IdInterno = Annotated[int | None, Depends(resolver_id_interno)]


def exigir_id_interno(id_interno: int | None) -> int:
    if id_interno is None:
        raise problema(
            403,
            "USUARIO_INTERNO_NO_VINCULADO",
            "Su usuario no está habilitado para esta operación.",
        )
    return id_interno


def exigir_agencia(usuario: Usuario) -> str:
    agencia = usuario.agencia()
    if agencia is None:
        raise problema(
            403, "AGENCIA_NO_ASIGNADA", "Su usuario no tiene una agencia asignada."
        )
    return agencia


@dataclass
class RegistroAuditado:
    """Lo completa la operación cuando conoce el id del registro creado."""

    id_registro: str | None = None


def _codigo_fallo(exc: BaseException) -> str:
    if isinstance(exc, StarletteHTTPException) and isinstance(exc.detail, dict):
        return str(exc.detail.get("code", exc.status_code))
    return type(exc).__name__


@contextmanager
def auditar(
    accion: str,
    tabla: str,
    usuario: Usuario,
    ip: str,
    detalle: str,
    id_registro: str | None = None,
) -> Iterator[RegistroAuditado]:
    """Audita el éxito o el fallo de una operación, en SeguridadDB.

    UsuarioID va en NULL igual que en auth: el id de WorkOS no es el UsuarioID de
    SeguridadDB y una FK fallida haría perder el evento. El id de WorkOS va en la
    descripción. `detalle` solo lleva ids y estados, nunca datos personales.
    La auditoría es best-effort (audit.registrar): no reemplaza la persistencia
    financiera, que la garantiza la transacción de la BD.
    """
    registro = RegistroAuditado(id_registro)
    try:
        yield registro
    except BaseException as exc:
        audit.registrar(
            audit.EventoAuditoria(
                accion=accion,
                tabla=tabla,
                id_registro=registro.id_registro,
                resultado="Fallido",
                usuario=None,
                ip=ip,
                descripcion=(
                    f"usuario={usuario.id_usuario} {detalle} motivo={_codigo_fallo(exc)}"
                ),
                roles=usuario.roles_texto(),
            )
        )
        raise
    audit.registrar(
        audit.EventoAuditoria(
            accion=accion,
            tabla=tabla,
            id_registro=registro.id_registro,
            resultado="Exitoso",
            usuario=None,
            ip=ip,
            descripcion=f"usuario={usuario.id_usuario} {detalle}",
            roles=usuario.roles_texto(),
        )
    )
