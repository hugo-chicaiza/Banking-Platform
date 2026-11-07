"""Reglas de negocio de Caja.

Las consultas respetan los permisos de WorkOS y el aislamiento por agencia.
Las operaciones de escritura deben ejecutarse en transacciones de BD.
"""

import json
from collections.abc import Mapping
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import Connection

from app.core.api.errors import problema
from app.core.security.auth import Usuario
from app.core.security.operador import auditar, exigir_agencia, exigir_id_interno
from app.modules.caja import repository as repo
from app.modules.caja.repository import Fila
from app.modules.caja.schemas import (
    CajaFisica,
    CuadreCaja,
    CuadreCajaCreate,
    Desglose,
    Dotacion,
    DotacionRequest,
    Jornada,
    JornadaOpen,
    MovimientoCaja,
    PageJornada,
    PageMovimientoCaja,
)

ROLES_GLOBALES = frozenset({"CONTADOR", "AUDITOR", "ADMIN"})


def agencia_consultable(
    usuario: Usuario,
    pedida: str | None,
    roles_globales: frozenset[str],
) -> str | None:
    """Determina qué agencia puede consultar un usuario.

    Los roles globales pueden consultar cualquier agencia.
    Los demás usuarios solamente pueden consultar su agencia asignada.
    """

    if set(usuario.roles) & roles_globales:
        return pedida

    propia = exigir_agencia(usuario)

    if pedida is not None and pedida != propia:
        raise problema(
            403,
            "SIN_ACCESO_AGENCIA",
            "No tiene acceso a los datos de esa agencia.",
        )

    return propia


def _caja(fila: Fila) -> CajaFisica:
    """Convierte una fila SQL al modelo CajaFisica."""

    return CajaFisica(
        id_caja_fisica=fila["IdCajaFisica"],
        id_agencia=fila["IdAgencia"],
        codigo_caja=fila["CodigoCaja"],
        estado=fila["Estado"],
        descripcion_estado=fila["DescripcionEstado"],
        limite_efectivo_caja=fila["LimiteEfectivoCaja"],
    )


# ---------------------------------------------------------------------
# CAJ-01: Listado de cajas físicas
# ---------------------------------------------------------------------


def listar_cajas_fisicas(
    conn: Connection,
    usuario: Usuario,
    id_agencia: str | None,
    activa: bool | None,
) -> list[CajaFisica]:
    """Lista cajas físicas según los permisos de agencia."""

    agencia = agencia_consultable(
        usuario,
        id_agencia,
        frozenset({"ADMIN"}),
    )

    filas = repo.listar_cajas_fisicas(
        conn,
        agencia,
        activa,
    )

    return [_caja(fila) for fila in filas]


# ---------------------------------------------------------------------
# CAJ-02: Consulta de jornadas
# ---------------------------------------------------------------------


SORT_JORNADAS = frozenset(
    {
        "idJornadaCaja",
        "idUsuario",
        "idCajaFisica",
        "idAgencia",
        "fechaHoraApertura",
        "fechaHoraCierre",
        "dineroInicial",
        "estado",
    }
)


def _jornada(fila: Fila) -> Jornada:
    """Convierte una fila SQL al modelo Jornada."""

    return Jornada(
        id_jornada_caja=fila["IdJornadaCaja"],
        id_usuario=fila["IdUsuario"],
        id_caja_fisica=fila["IdCajaFisica"],
        id_agencia=fila["IdAgencia"].strip(),
        fecha_hora_apertura=fila["FechaHoraApertura"],
        fecha_hora_cierre=fila["FechaHoraCierre"],
        dinero_inicial=fila["DineroInicial"],
        estado=fila["Estado"],
        observacion=fila["Observacion"],
    )


def listar_jornadas(
    conn: Connection,
    *,
    usuario: Usuario,
    id_agencia: str | None,
    id_usuario: int | None,
    estado: str | None,
    desde: date | None,
    hasta: date | None,
    page: int,
    page_size: int,
    sort: str,
) -> PageJornada:
    """Consulta paginada de jornadas con restricciones por agencia."""

    # Validar agencia autorizada.
    agencia = agencia_consultable(
        usuario,
        id_agencia,
        frozenset({"CONTADOR", "AUDITOR"}),
    )

    # Validar rango de fechas.
    if desde is not None and hasta is not None and desde > hasta:
        raise problema(
            400,
            "RANGO_FECHAS_INVALIDO",
            "La fecha desde no puede ser posterior a hasta.",
        )

    if hasta == date.max:
        raise problema(
            400,
            "FECHA_HASTA_INVALIDA",
            "La fecha hasta está fuera del rango permitido.",
        )

    # Validar ordenamiento permitido.
    partes = sort.split(",")

    if (
        len(partes) != 2
        or partes[0] not in SORT_JORNADAS
        or partes[1] not in {"asc", "desc"}
    ):
        raise problema(
            400,
            "ORDEN_INVALIDO",
            "El ordenamiento solicitado no es válido.",
        )

    # Consultar únicamente la agencia autorizada.
    filas, total = repo.listar_jornadas(
        conn,
        id_agencia=agencia,
        id_usuario=id_usuario,
        estado=estado,
        desde=desde,
        hasta=hasta,
        page=page,
        page_size=page_size,
        sort=sort,
    )

    return PageJornada(
        items=[_jornada(fila) for fila in filas],
        page=page,
        page_size=page_size,
        total=total,
    )


# --- CAJ-05: detalle de jornada ---


def jornada_no_encontrada() -> Exception:
    return problema(
        404,
        "JORNADA_NO_ENCONTRADA",
        "La jornada no existe.",
    )


def verificar_alcance(
    usuario: Usuario,
    id_interno: int | None,
    jornada: Fila,
    permitidos: tuple[str, ...],
) -> str:
    """Comprueba acceso global, por agencia o por propiedad de jornada."""

    roles = set(usuario.roles) & set(permitidos)

    if roles & ROLES_GLOBALES:
        return "GLOBAL"

    if "SUPERVISOR" in roles:
        if jornada["IdAgencia"] == exigir_agencia(usuario):
            return "SUPERVISOR"
        raise jornada_no_encontrada()

    if "CAJERO" in roles:
        if jornada["IdUsuario"] == exigir_id_interno(id_interno):
            return "CAJERO"
        raise jornada_no_encontrada()

    raise problema(
        403,
        "SIN_PERMISO",
        "No tiene permiso para esta operación.",
    )


ROLES_CONSULTA_JORNADA = ("CAJERO", "SUPERVISOR", "CONTADOR")


def jornada_visible(
    conn: Connection,
    usuario: Usuario,
    id_interno: int | None,
    id_jornada: int,
    permitidos: tuple[str, ...] = ROLES_CONSULTA_JORNADA,
) -> Fila:
    fila = repo.obtener_jornada(conn, id_jornada)

    if fila is None:
        raise jornada_no_encontrada()

    verificar_alcance(
        usuario,
        id_interno,
        fila,
        permitidos,
    )

    return fila


def obtener_jornada(
    conn: Connection,
    usuario: Usuario,
    id_interno: int | None,
    id_jornada: int,
) -> Jornada:
    return _jornada(jornada_visible(conn, usuario, id_interno, id_jornada))


# --- CAJ-08: dotaciones de la jornada ----------


def _dotacion(fila: Fila, bajo_minimo: bool | None = None) -> Dotacion:
    return Dotacion(
        id_dotacion_caja=fila["IdDotacionCaja"],
        id_jornada_caja=fila["IdJornadaCaja"],
        id_boveda=fila["IdBoveda"],
        tipo_dotacion=fila["TipoDotacion"],
        monto=fila["Monto"],
        id_movimiento_boveda=fila["IdMovimientoBoveda"],
        boveda_bajo_minimo=bajo_minimo,
        estado=fila["Estado"],
    )


def listar_dotaciones(
    conn: Connection,
    usuario: Usuario,
    id_interno: int | None,
    id_jornada: int,
) -> list[Dotacion]:
    jornada_visible(conn, usuario, id_interno, id_jornada)
    return [_dotacion(fila) for fila in repo.listar_dotaciones(conn, id_jornada)]


# --- CAJ-12: movimientos de caja ----------


def orden_desde_texto(
    sort: str | None,
    permitidos: Mapping[str, str],
    defecto: tuple[str, str],
) -> tuple[str, str]:
    """Valida el orden solicitado mediante una lista blanca."""
    if sort is None:
        return defecto

    campo, _, direccion = sort.partition(",")
    direccion = direccion or "asc"

    if campo not in permitidos or direccion not in ("asc", "desc"):
        raise problema(
            400,
            "ORDEN_INVALIDO",
            "El orden solicitado no es válido.",
        )

    return campo, direccion


def rango_fechas(
    desde: date | None,
    hasta: date | None,
) -> tuple[datetime | None, datetime | None]:
    """Convierte fechas a intervalos de días completos."""
    if desde is not None and hasta is not None and desde > hasta:
        raise problema(
            400,
            "RANGO_FECHAS_INVALIDO",
            "La fecha desde es posterior a hasta.",
        )

    inicio = datetime.combine(desde, time.min) if desde is not None else None

    fin = (
        datetime.combine(hasta + timedelta(days=1), time.min)
        if hasta is not None
        else None
    )

    return inicio, fin


def listar_movimientos(
    conn: Connection,
    usuario: Usuario,
    id_interno: int | None,
    id_jornada: int,
    page: int,
    page_size: int,
    sort: str | None,
) -> PageMovimientoCaja:
    jornada_visible(conn, usuario, id_interno, id_jornada)

    orden = orden_desde_texto(
        sort,
        repo.ORDEN_MOVIMIENTOS,
        ("fechaHora", "asc"),
    )

    filas, total = repo.listar_movimientos(
        conn,
        id_jornada,
        orden,
        (page - 1) * page_size,
        page_size,
    )

    return PageMovimientoCaja(
        items=[
            MovimientoCaja(
                id_movimiento_caja=f["IdMovimientoCaja"],
                id_transaccion=f["IdTransaccion"],
                id_jornada_caja=f["IdJornadaCaja"],
                id_tipo_movimiento=f["IdTipoMovimiento"],
                codigo_tipo_movimiento=f["CodigoTipoMovimiento"],
                naturaleza=f["Naturaleza"],
                monto=f["Monto"],
                fecha_hora=f["FechaHora"],
                observacion=f["Observacion"],
                id_asiento_contable=f["IdAsientoContable"],
            )
            for f in filas
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


# --- CAJ-14: consultar cuadre ----------


def decimal(valor: Any) -> Decimal:
    return valor if isinstance(valor, Decimal) else Decimal(str(valor))


CENTAVO = Decimal("0.01")


def saldo_esperado(totales: Mapping[str, Any]) -> Decimal:
    """Inicial + dotaciones + depósitos + pagos - retiros - devoluciones."""
    esperado = (
        decimal(totales["SaldoInicial"])
        + decimal(totales["TotalDotaciones"])
        + decimal(totales["TotalDepositos"])
        + decimal(totales["TotalPagos"])
        - decimal(totales["TotalRetiros"])
        - decimal(totales["TotalDevolucionesBoveda"])
    )
    return esperado.quantize(CENTAVO, rounding=ROUND_HALF_UP)


def estado_por_diferencia(diferencia: Decimal) -> str:
    if diferencia == 0:
        return "CUADRADO"
    return "SOBRANTE" if diferencia > 0 else "FALTANTE"


def _cuadre(fila: Fila) -> CuadreCaja:
    return CuadreCaja(
        id_cuadre_caja=fila["IdCuadreCaja"],
        id_jornada_caja=fila["IdJornadaCaja"],
        id_usuario=fila["IdUsuario"],
        fecha_hora_cuadre=fila["FechaHoraCuadre"],
        saldo_inicial=fila["SaldoInicial"],
        total_dotaciones=fila["TotalDotaciones"],
        total_depositos=fila["TotalDepositos"],
        total_retiros=fila["TotalRetiros"],
        total_pagos=fila["TotalPagos"],
        total_devoluciones_boveda=fila["TotalDevolucionesBoveda"],
        saldo_esperado=saldo_esperado(fila),
        saldo_final_fisico=fila["SaldoFinalFisico"],
        diferencia_dinero=fila["DiferenciaDinero"],
        estado_cuadre=fila["EstadoCuadre"],
        id_autorizado_por=fila["IdAutorizadoPor"],
        id_fecha_contable=fila["IdFechaContable"],
        observaciones=fila["Observaciones"],
    )


def cuadre_no_encontrado() -> Exception:
    return problema(
        404,
        "CUADRE_NO_ENCONTRADO",
        "La jornada no tiene cuadre.",
    )


def obtener_cuadre(
    conn: Connection,
    usuario: Usuario,
    id_interno: int | None,
    id_jornada: int,
) -> CuadreCaja:
    jornada_visible(conn, usuario, id_interno, id_jornada)

    fila = repo.obtener_cuadre_de_jornada(conn, id_jornada)

    if fila is None:
        raise cuadre_no_encontrado()

    return _cuadre(fila)


# --- CAJ-06: cancelación de jornada ----------


def jornada_bloqueada(
    conn: Connection,
    id_jornada: int,
) -> Fila:
    jornada = repo.obtener_jornada(
        conn,
        id_jornada,
        bloquear=True,
    )

    if jornada is None:
        raise jornada_no_encontrada()

    return jornada


def _recargar_jornada(
    conn: Connection,
    id_jornada: int,
) -> Jornada:
    fila = repo.obtener_jornada(conn, id_jornada)

    if fila is None:
        raise RuntimeError("La jornada desapareció dentro de la transacción")

    return _jornada(fila)


def cancelar_jornada(
    conn: Connection,
    usuario: Usuario,
    id_jornada: int,
    motivo: str,
    ip: str,
) -> Jornada:
    with (
        auditar(
            "CANCELAR_JORNADA",
            "Caja.JornadasCaja",
            usuario,
            ip,
            f"jornada={id_jornada}",
            str(id_jornada),
        ),
        conn.begin(),
    ):
        jornada = jornada_bloqueada(
            conn,
            id_jornada,
        )

        verificar_alcance(
            usuario,
            None,
            jornada,
            ("SUPERVISOR",),
        )

        if jornada["Estado"] != "ABIERTA":
            raise problema(
                409,
                "JORNADA_NO_ABIERTA",
                "La jornada no está ABIERTA.",
            )

        if repo.jornada_tiene_actividad(
            conn,
            id_jornada,
        ):
            raise problema(
                409,
                "JORNADA_CON_MOVIMIENTOS",
                "La jornada ya tiene movimientos.",
            )

        if not repo.cancelar_jornada(
            conn,
            id_jornada,
            motivo,
        ):
            raise problema(
                409,
                "JORNADA_NO_ABIERTA",
                "La jornada no está ABIERTA.",
            )

        return _recargar_jornada(
            conn,
            id_jornada,
        )


# --- CAJ-03: apertura de jornada ----------


def abrir_jornada(
    conn: Connection,
    usuario: Usuario,
    id_interno: int | None,
    datos: JornadaOpen,
    ip: str,
) -> Jornada:
    with auditar(
        "ABRIR_JORNADA",
        "Caja.JornadasCaja",
        usuario,
        ip,
        f"caja={datos.id_caja_fisica}",
    ) as registro:
        id_cajero = exigir_id_interno(id_interno)

        with conn.begin():
            caja = repo.obtener_caja_fisica(
                conn,
                datos.id_caja_fisica,
            )

            if caja is None:
                raise problema(
                    422,
                    "CAJA_FISICA_NO_ENCONTRADA",
                    "La caja física no existe.",
                )

            if not repo.cajero_asignado(
                conn,
                id_cajero,
                caja["IdAgencia"],
            ):
                raise problema(
                    409,
                    "CAJERO_NO_ASIGNADO_A_AGENCIA",
                    "No tiene asignación vigente en la agencia de la caja.",
                )

            if (
                repo.jornada_abierta_de_usuario(
                    conn,
                    id_cajero,
                )
                is not None
            ):
                raise problema(
                    409,
                    "CAJERO_YA_TIENE_JORNADA_ABIERTA",
                    "Ya tiene una jornada abierta.",
                )

            if (
                repo.jornada_abierta_de_caja(
                    conn,
                    datos.id_caja_fisica,
                )
                is not None
            ):
                raise problema(
                    409,
                    "CAJA_EN_USO",
                    "La caja física ya tiene una jornada abierta.",
                )

            if not caja["Estado"]:
                raise problema(
                    409,
                    "CAJA_INACTIVA",
                    "La caja física no está activa.",
                )

            id_jornada = repo.insertar_jornada(
                conn,
                id_cajero,
                datos.id_caja_fisica,
                caja["IdAgencia"],
                datos.dinero_inicial,
                datos.observacion,
            )

            registro.id_registro = str(id_jornada)

            return _recargar_jornada(
                conn,
                id_jornada,
            )


# --- CAJ-04: jornada actual del cajero ----------


def jornada_actual(
    conn: Connection,
    id_interno: int | None,
) -> Jornada:
    fila = repo.jornada_abierta_de_usuario(
        conn,
        exigir_id_interno(id_interno),
        bloquear=False,
    )

    if fila is None:
        raise problema(
            404,
            "SIN_JORNADA_ABIERTA",
            "No tiene una jornada abierta.",
        )

    return _jornada(fila)


# --- CAJ-07: dotación ----------


def desglose_json(desglose: list[Desglose]) -> str:
    return json.dumps(
        [
            {
                "IdDenominacion": d.id_denominacion,
                "Cantidad": d.cantidad,
            }
            for d in desglose
        ]
    )


def fecha_contable(conn: Connection) -> int:
    id_fecha = repo.id_fecha_contable(conn)

    if id_fecha is None:
        raise problema(
            500,
            "CALENDARIO_SIN_FECHA",
            "El calendario contable no tiene fechas cargadas para este período",
        )

    return id_fecha


def validar_custodia(
    modo: str,
    actor: int,
    autorizado_por: int,
    id_cajero: int,
) -> None:
    if autorizado_por == id_cajero:
        raise problema(
            409,
            "DOBLE_CUSTODIA_VIOLADA",
            "Quien autoriza debe ser distinto del cajero.",
        )

    if modo == "SUPERVISOR" and autorizado_por != actor:
        raise problema(
            422,
            "AUTORIZADOR_NO_COINCIDE",
            "autorizadoPor debe ser el usuario que autoriza.",
        )


def registrar_dotacion(
    conn: Connection,
    usuario: Usuario,
    id_interno: int | None,
    id_jornada: int,
    datos: DotacionRequest,
    ip: str,
) -> Dotacion:
    with auditar(
        "REGISTRAR_DOTACION",
        "Caja.DotacionesCaja",
        usuario,
        ip,
        f"jornada={id_jornada} tipo={datos.tipo_dotacion} boveda={datos.id_boveda}",
    ) as registro:
        actor = exigir_id_interno(id_interno)

        with conn.begin():
            jornada = jornada_bloqueada(conn, id_jornada)

            modo = verificar_alcance(
                usuario,
                actor,
                jornada,
                ("CAJERO", "SUPERVISOR"),
            )

            if jornada["Estado"] != "ABIERTA":
                raise problema(
                    409,
                    "JORNADA_NO_ABIERTA",
                    "La jornada no está ABIERTA.",
                )

            validar_custodia(
                modo,
                actor,
                datos.autorizado_por,
                jornada["IdUsuario"],
            )

            salida = repo.registrar_dotacion(
                conn,
                id_jornada,
                datos.id_boveda,
                datos.autorizado_por,
                datos.tipo_dotacion,
                desglose_json(datos.desglose),
                datos.observacion,
                fecha_contable(conn),
            )

            id_dotacion = int(salida["IdDotacionCaja"])
            registro.id_registro = str(id_dotacion)

            fila = repo.obtener_dotacion(conn, id_dotacion)

            if fila is None:
                raise RuntimeError("La dotación no se encontró tras registrarla")

            return _dotacion(
                fila,
                bool(salida["BovedaBajoMinimo"]),
            )


# --- CAJ-13: generar cuadre ----------


def _recargar_cuadre(conn: Connection, id_cuadre: int) -> CuadreCaja:
    fila = repo.obtener_cuadre(conn, id_cuadre)

    if fila is None:
        raise RuntimeError("El cuadre desapareció dentro de la transacción")

    return _cuadre(fila)


def _totales(conn: Connection, id_jornada: int) -> Fila:
    totales = repo.calcular_totales(conn, id_jornada)

    if totales is None:
        raise jornada_no_encontrada()

    return totales


def generar_cuadre(
    conn: Connection,
    usuario: Usuario,
    id_interno: int | None,
    id_jornada: int,
    datos: CuadreCajaCreate,
    ip: str,
) -> CuadreCaja:
    with auditar(
        "GENERAR_CUADRE",
        "Caja.CuadreCaja",
        usuario,
        ip,
        f"jornada={id_jornada}",
    ) as registro:
        exigir_id_interno(id_interno)

        with conn.begin():
            jornada = jornada_bloqueada(conn, id_jornada)

            verificar_alcance(
                usuario,
                id_interno,
                jornada,
                ("CAJERO",),
            )

            if jornada["Estado"] == "CANCELADA":
                raise problema(
                    409,
                    "JORNADA_CANCELADA",
                    "La jornada está CANCELADA.",
                )

            if jornada["Estado"] != "ABIERTA":
                raise problema(
                    409,
                    "JORNADA_NO_ABIERTA",
                    "La jornada no está ABIERTA.",
                )

            if repo.obtener_cuadre_de_jornada(
                conn,
                id_jornada,
                bloquear=True,
            ):
                raise problema(
                    409,
                    "CUADRE_YA_EXISTE",
                    "La jornada ya tiene un cuadre.",
                )

            id_cuadre = repo.insertar_cuadre(
                conn,
                id_jornada,
                jornada["IdUsuario"],
                _totales(conn, id_jornada),
                fecha_contable(conn),
                datos.observaciones,
            )

            registro.id_registro = str(id_cuadre)

            return _recargar_cuadre(conn, id_cuadre)
