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
from dataclasses import dataclass, field
from typing import Annotated, Any
from uuid import uuid4

from fastapi import Depends
from sqlalchemy import Connection, text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.api.errors import problema
from app.core.config.logs import trace_id_actual
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


def exigir_agencia_autorizada(usuario: Usuario, agencia: str) -> str:
    admin_global = "ADMIN" in usuario.roles and not (
        {"CAJERO", "ASESOR"} & set(usuario.roles)
    )
    if not admin_global and agencia not in usuario.agencias_permitidas():
        raise problema(403, "SIN_ACCESO_AGENCIA", "No tiene acceso a esa agencia.")
    return agencia


def agencia_de_consulta(usuario: Usuario, pedida: str | None) -> str | None:
    if "ADMIN" in usuario.roles and not ({"CAJERO", "ASESOR"} & set(usuario.roles)):
        return pedida
    seleccion = pedida if pedida is not None else exigir_agencia(usuario)
    return exigir_agencia_autorizada(usuario, seleccion)


@dataclass
class RegistroAuditado:
    """Lo completa la operación cuando conoce el id del registro creado.

    `detalle` agrega datos que solo se conocen dentro de la operación (por ejemplo,
    el valor anterior de un campo que se reescribe). Mismas reglas que `detalle` de
    auditar(): ids, estados y montos; nunca datos personales.
    """

    id_registro: str | None = None
    detalle: str = ""
    # Lo llena auditar(); confirmar() lo usa para escribir el evento en la bandeja
    _evento: dict[str, Any] = field(default_factory=dict, repr=False)
    _confirmado: bool = field(default=False, repr=False)

    def confirmar(
        self,
        conn: Connection,
        *,
        cambios: dict[str, Any] | None = None,
        objetivo: str | None = None,
        id_objetivo: str | None = None,
    ) -> None:
        """E0-05 B: escribe el evento de éxito en `Auditoria.EventoPendiente` **dentro de la
        transacción abierta de la operación**. Si el evento no se puede guardar, la operación
        se revierte; si la operación se revierte, el evento tampoco queda. El relevo lo pasa
        a la bitácora. `objetivo`/`id_objetivo`: tabla e id del registro al que apunta el
        evento (por omisión, la tabla de auditar() y `id_registro`). Operaciones con clientes
        apuntan a Transacciones.Transaccion; las internas, a su tabla de movimiento.
        Se llama justo antes de salir del `with conn.begin()`; montos, ids y estados, nunca
        datos personales."""
        if not conn.in_transaction():
            raise RuntimeError(
                "confirmar() exige la transacción abierta de la operación"
            )
        # Importación diferida: aprobaciones depende de core, no al revés en la carga
        from app.modules.aprobaciones.congelacion import congelar

        e = self._evento
        usuario: Usuario = e["usuario"]
        tabla = objetivo or e["tabla"]
        descripcion = _descripcion(usuario, e["detalle"], self)
        contenido = congelar(
            {
                "codigo": e["accion"],
                "sujeto": usuario.id_usuario,
                "idInterno": None,  # mismo criterio que auditar(): sin FK que pierda el evento
                "organizacion": usuario.id_organizacion,
                "roles": list(usuario.roles),
                "agencia": _agencia_leida(usuario),
                "sesion": usuario.id_sesion,
                "origen": e["ip"] or "",
                "correlacion": trace_id_actual.get() or "",
                "canal": "API",
                "tipoObjetivo": tabla,
                "tablaAfectada": tabla,
                "agenciaActor": _agencia_leida(usuario),
                "idSolicitud": None,
                "idObjetivo": id_objetivo or self.id_registro or "",
                "resultado": "Exitoso",
                "descripcion": audit.texto_seguro(descripcion),
                "cambios": cambios or {},
            }
        ).texto
        conn.execute(
            text(
                "INSERT Auditoria.EventoPendiente(IdEvento,CodigoEvento,Contenido) VALUES(:id,:codigo,:contenido)"
            ),
            {"id": str(uuid4()), "codigo": e["accion"], "contenido": contenido},
        )
        self._confirmado = True


def _agencia_leida(usuario: Usuario) -> str | None:
    """Agencia del usuario para la auditoría sin consultar la base: la que la operación
    ya leyó en esta petición (agencia()) o la fija de las pruebas."""
    valor = usuario._leidos.get("agencia", usuario.id_agencia)
    return valor if isinstance(valor, str) else None


def _descripcion(usuario: Usuario, detalle: str, registro: RegistroAuditado) -> str:
    extra = f" {registro.detalle}" if registro.detalle else ""
    return f"usuario={usuario.id_usuario} {detalle}{extra}"


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
    Sin confirmar(), la auditoría es best-effort (audit.registrar). Las operaciones de
    dinero llaman registro.confirmar(conn) dentro de su transacción (E0-05 B): el evento
    de éxito queda en la bandeja junto con el movimiento, o ninguno de los dos. Los fallos
    siguen siendo best-effort: la transacción ya se revirtió.
    """
    registro = RegistroAuditado(id_registro)
    registro._evento = {
        "accion": accion,
        "tabla": tabla,
        "usuario": usuario,
        "ip": ip,
        "detalle": detalle,
    }
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
                    f"{_descripcion(usuario, detalle, registro)}"
                    f" motivo={_codigo_fallo(exc)}"
                ),
                roles=usuario.roles_texto(),
                agencia=_agencia_leida(usuario),
                sesion=getattr(usuario, "id_sesion", None),
            )
        )
        raise
    if registro._confirmado:
        return  # E0-05 B: el evento ya quedó en la bandeja con la operación
    audit.registrar(
        audit.EventoAuditoria(
            accion=accion,
            tabla=tabla,
            id_registro=registro.id_registro,
            resultado="Exitoso",
            usuario=None,
            ip=ip,
            descripcion=_descripcion(usuario, detalle, registro),
            roles=usuario.roles_texto(),
            agencia=_agencia_leida(usuario),
            sesion=getattr(usuario, "id_sesion", None),
        )
    )
