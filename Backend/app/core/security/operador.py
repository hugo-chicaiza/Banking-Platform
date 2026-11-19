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
from decimal import Decimal
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


# E0-05 B: montos que el evento lleva en `cambios`, leídos del mismo registro al que
# apunta y dentro de la misma transacción (coinciden con lo guardado). Solo montos,
# saldos y roles; sin números de cuenta ni datos del cliente.
_MONTOS: dict[str, str] = {
    "Transacciones.Transaccion": (
        "SELECT t.Monto AS monto, m.RolCuenta AS rolCuenta, m.TipoMovimiento AS tipo, "
        "m.Monto AS montoCuenta, m.SaldoAnterior AS saldoAnterior, m.SaldoPosterior AS saldoPosterior "
        "FROM Transacciones.Transaccion t "
        "LEFT JOIN Cuentas.MovimientoTransaccion m ON m.IdTransaccion = t.IdTransaccion "
        "WHERE t.IdTransaccion = :id"
    ),
    "Boveda.MovimientoBoveda": (
        "SELECT Monto AS monto, TipoMovimiento AS tipo, SaldoAnterior AS saldoAnterior, "
        "SaldoPosterior AS saldoPosterior FROM Boveda.MovimientoBoveda WHERE IdMovimiento = :id"
    ),
    "Caja.JornadasCaja": "SELECT DineroInicial AS dineroInicial FROM Caja.JornadasCaja WHERE IdJornadaCaja = :id",
    "Caja.CuadreCaja": (
        "SELECT SaldoInicial AS saldoInicial, TotalDepositos AS totalDepositos, TotalRetiros AS totalRetiros, "
        "TotalPagos AS totalPagos, TotalDotaciones AS totalDotaciones, "
        "TotalDevolucionesBoveda AS totalDevoluciones, SaldoFinalFisico AS saldoFinalFisico, "
        "DiferenciaDinero AS diferencia FROM Caja.CuadreCaja WHERE IdCuadreCaja = :id"
    ),
    "Boveda.ArqueoBoveda": (
        "SELECT SaldoTeorico AS saldoTeorico, SaldoFisico AS saldoFisico "
        "FROM Boveda.ArqueoBoveda WHERE IdArqueoBoveda = :id"
    ),
    "Boveda.SolicitudMovimientoBoveda": (
        "SELECT Monto AS monto FROM Boveda.SolicitudMovimientoBoveda WHERE IdSolicitudMovimiento = :id"
    ),
}


def _json(valor: Any) -> Any:
    return str(valor) if isinstance(valor, Decimal) else valor


def montos(conn: Connection, tabla: str, ids: str) -> dict[str, Any]:
    """Montos del registro (o registros, ids separados por coma) al que apunta el evento."""
    sql = _MONTOS.get(tabla)
    if sql is None or not ids:
        return {}
    filas = []
    for id_ in ids.split(","):
        if not id_.strip().isdigit():
            continue
        resultado = conn.execute(text(sql), {"id": int(id_)}).mappings().all()
        filas += [
            {k: _json(v) for k, v in dict(f).items() if v is not None}
            for f in resultado
        ]
    if tabla == "Transacciones.Transaccion" and filas:
        cuentas = [
            {k: f[k] for k in f if k != "monto"} for f in filas if "rolCuenta" in f
        ]
        return {"monto": filas[0].get("monto"), "cuentas": cuentas}
    if len(filas) == 1:
        return filas[0]
    return {"movimientos": filas} if filas else {}


def encolar_evento(
    conn: Connection,
    *,
    codigo: str,
    sujeto: str,
    organizacion: str | None,
    roles: list[str],
    agencia: str | None,
    sesion: str,
    origen: str,
    canal: str,
    tabla: str,
    id_objetivo: str,
    descripcion: str,
    cambios: dict[str, Any] | None = None,
) -> None:
    """E0-05 B: escribe un evento de éxito en `Auditoria.EventoPendiente` **dentro de la
    transacción abierta de la operación** (los dos o ninguno); el relevo lo pasa a la
    bitácora. Agrega los montos del registro al que apunta (`tabla`, `id_objetivo`).
    Lo usan RegistroAuditado.confirmar (operadores) y atm.auditoria (terminales)."""
    if not conn.in_transaction():
        raise RuntimeError("el evento exige la transacción abierta de la operación")
    # Importación diferida: aprobaciones depende de core, no al revés en la carga
    from app.modules.aprobaciones.congelacion import congelar

    contenido = congelar(
        {
            "codigo": codigo,
            "sujeto": sujeto,
            "idInterno": None,  # sin FK a Organizacion.Usuarios que pueda perder el evento
            "organizacion": organizacion,
            "roles": roles,
            "agencia": agencia,
            "sesion": sesion,
            "origen": origen,
            "correlacion": trace_id_actual.get() or "",
            "canal": canal,
            "tipoObjetivo": tabla,
            "tablaAfectada": tabla,
            "agenciaActor": agencia,
            "idSolicitud": None,
            "idObjetivo": id_objetivo,
            "resultado": "Exitoso",
            "descripcion": audit.texto_seguro(descripcion),
            "cambios": {**montos(conn, tabla, id_objetivo), **(cambios or {})},
        }
    ).texto
    conn.execute(
        text(
            "INSERT Auditoria.EventoPendiente(IdEvento,CodigoEvento,Contenido) VALUES(:id,:codigo,:contenido)"
        ),
        {"id": str(uuid4()), "codigo": codigo, "contenido": contenido},
    )


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
        e = self._evento
        usuario: Usuario = e["usuario"]
        encolar_evento(
            conn,
            codigo=e["accion"],
            sujeto=usuario.id_usuario,
            organizacion=usuario.id_organizacion,
            roles=list(usuario.roles),
            agencia=_agencia_leida(usuario),
            sesion=usuario.id_sesion,
            origen=e["ip"] or "",
            canal="API",
            tabla=objetivo or e["tabla"],
            id_objetivo=id_objetivo or self.id_registro or "",
            descripcion=_descripcion(usuario, e["detalle"], self),
            cambios=cambios,
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
