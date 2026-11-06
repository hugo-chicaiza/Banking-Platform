"""Consulta y reverso supervisado de transacciones."""

from datetime import date

from sqlalchemy import Connection

from app.core.api.errors import problema
from app.core.security.auth import Usuario
from app.core.security.operador import exigir_agencia
from app.modules.caja.service import (
    agencia_consultable,
    orden_desde_texto,
    rango_fechas,
)
from app.modules.transacciones import repository as repo
from app.modules.transacciones.repository import Fila
from app.modules.transacciones.schemas import PageTransaccion, Transaccion

# Roles que ven transacciones de todas las agencias. SUPERVISOR: solo la suya.
ROLES_GLOBALES = frozenset({"AUDITOR", "CONTADOR", "ADMIN"})


def _transaccion(fila: Fila) -> Transaccion:
    return Transaccion(
        id_transaccion=fila["IdTransaccion"],
        numero_comprobante=fila["NumeroComprobante"],
        registro_unico=fila["RegistroUnico"],
        mti=fila["MTI"],
        stan=fila["STAN"],
        rrn=fila["RRN"],
        tipo_operacion=fila["TipoOperacion"],
        tipo_transaccion=fila["TipoTransaccion"],
        id_cuenta=fila["IdCuenta"],
        id_cuenta_destino=fila["IdCuentaDestino"],
        id_tarjeta=fila["IdTarjeta"],
        id_canal=fila["IdCanal"],
        id_terminal=fila["IdTerminal"],
        id_agencia=fila["IdAgencia"],
        id_jornada_caja=fila["IdJornadaCaja"],
        id_transaccion_relacionada=fila["IdTransaccionRelacionada"],
        monto=fila["Monto"],
        codigo_respuesta=fila["CodigoRespuesta"],
        estado=fila["Estado"],
        id_fecha_contable=fila["IdFechaContable"],
        fecha_hora_sistema=fila["FechaHoraSistema"],
        creado_por=fila["CreadoPor"],
    )


# --- TRX-01 --------------------------------------------------------------------------


def listar_transacciones(
    conn: Connection,
    usuario: Usuario,
    id_cuenta: int | None,
    tipo_transaccion: str | None,
    estado: str | None,
    id_canal: int | None,
    id_agencia: str | None,
    desde: date | None,
    hasta: date | None,
    page: int,
    page_size: int,
    sort: str | None,
) -> PageTransaccion:
    alcance = None
    if not set(usuario.roles) & ROLES_GLOBALES:
        # SUPERVISOR: pedir otra agencia es 403; sin filtro, se limita a la suya
        alcance = agencia_consultable(usuario, id_agencia, ROLES_GLOBALES)
    inicio, fin = rango_fechas(desde, hasta)
    orden = orden_desde_texto(sort, repo.ORDEN, ("fechaHoraSistema", "desc"))
    filas, total = repo.listar_transacciones(
        conn,
        {
            "id_cuenta": id_cuenta,
            "tipo_transaccion": tipo_transaccion,
            "estado": estado,
            "id_canal": id_canal,
            "id_agencia": id_agencia,
            "desde": inicio,
            "hasta": fin,
            "alcance": alcance,
        },
        orden,
        (page - 1) * page_size,
        page_size,
    )
    return PageTransaccion(
        items=[_transaccion(f) for f in filas],
        page=page,
        page_size=page_size,
        total=total,
    )


# --- TRX-02: detalle de transacción ----------


def transaccion_no_encontrada() -> Exception:
    return problema(
        404,
        "TRANSACCION_NO_ENCONTRADA",
        "La transacción no existe.",
    )


def verificar_alcance(usuario: Usuario, fila: Fila) -> None:
    """Oculta las transacciones fuera de la agencia del supervisor."""
    if set(usuario.roles) & ROLES_GLOBALES:
        return

    if fila["AgenciaOperacion"] != exigir_agencia(usuario):
        raise transaccion_no_encontrada()


def obtener_transaccion(
    conn: Connection,
    usuario: Usuario,
    id_transaccion: int,
) -> Transaccion:
    fila = repo.obtener_transaccion(conn, id_transaccion)

    if fila is None:
        raise transaccion_no_encontrada()

    verificar_alcance(usuario, fila)

    return _transaccion(fila)
