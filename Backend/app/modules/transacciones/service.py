"""Consulta y reverso supervisado de transacciones."""

from datetime import date
from decimal import Decimal

from sqlalchemy import Connection

from app.core.api.errors import problema
from app.core.security.auth import Usuario
from app.core.security.operador import auditar, exigir_agencia, exigir_id_interno
from app.modules.caja import repository as caja_repo
from app.modules.caja.service import (
    agencia_consultable,
    decimal,
    fecha_contable,
    orden_desde_texto,
    rango_fechas,
    saldo_esperado,
)
from app.modules.contabilidad.service import ahora_ecuador
from app.modules.transacciones import repository as repo
from app.modules.transacciones.dependencias import (
    DatosAsiento,
    DependenciasOperacion,
)
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


# --- TRX-03: reverso de transacciones ----------


_OPUESTO = {"C": "D", "D": "C"}

# Lo único que TRX-03 sabe deshacer por completo: movimiento de cuenta, comisión,
# asiento y efectivo de caja. Transferencias, créditos, tarjetas y ATM tienen
# efectos en otras tablas (cuenta destino, cuotas, gavetas) que este reverso no toca.
_TIPOS_REVERSABLES = frozenset({"Deposito", "Retiro"})

_LARGO_OBSERVACION_CAJA = 300  # Caja.MovimientosCaja.Observacion varchar(300)


def verificar_reverso_soportado(original: Fila, supervisor: int) -> None:
    """409 si el reverso dejaría efectos sin deshacer o si se autoaprueba."""
    if (
        original["TipoTransaccion"] not in _TIPOS_REVERSABLES
        or original["IdTerminal"] is not None
        or original["IdTarjeta"] is not None
        or original["IdCuentaDestino"] is not None
    ):
        raise problema(
            409,
            "REVERSO_NO_SOPORTADO",
            "Esta transacción se reversa por su canal o módulo de origen.",
        )

    if original["CreadoPor"] == supervisor:
        raise problema(
            409,
            "AUTORREVERSO_NO_PERMITIDO",
            "Quien reversa debe ser distinto de quien registró la transacción.",
        )


def verificar_cuentas_del_reverso(conn: Connection, movimientos: list[Fila]) -> None:
    """Bloquea cada cuenta afectada y comprueba que admita el movimiento contrario.

    Un crédito original se reversa con un débito: el disponible (Saldo -
    SaldoRetenido) debe cubrirlo, o el reverso dejaría la cuenta en negativo.
    """
    debitos: dict[int, Decimal] = {}
    for movimiento in movimientos:
        id_cuenta = int(movimiento["IdCuenta"])
        debito = (
            decimal(movimiento["Monto"])
            if _OPUESTO[str(movimiento["TipoMovimiento"]).strip()] == "D"
            else Decimal(0)
        )
        debitos[id_cuenta] = debitos.get(id_cuenta, Decimal(0)) + debito

    # Orden fijo de bloqueo para que dos reversos no se crucen
    for id_cuenta in sorted(debitos):
        cuenta = repo.obtener_cuenta(conn, id_cuenta)

        if cuenta is None or cuenta["Estado"] != "Activa":
            raise problema(
                409,
                "CUENTA_NO_ACTIVA",
                "La cuenta no está Activa.",
            )

        disponible = decimal(cuenta["Saldo"]) - decimal(cuenta["SaldoRetenido"])

        if debitos[id_cuenta] > disponible:
            raise problema(
                422,
                "FONDOS_INSUFICIENTES",
                "El disponible de la cuenta no cubre el reverso.",
            )


def verificar_efectivo_del_reverso(
    conn: Connection, id_jornada: int, caja: Fila | None
) -> None:
    """Reversar un depósito saca efectivo de la caja: debe existir.

    Un depósito o retiro de ventanilla sin Caja.MovimientosCaja es una anomalía
    (C06): reversarlo movería la cuenta sin mover el efectivo. Se detiene.
    """
    if caja is None:
        raise problema(
            409,
            "TRANSACCION_INCONSISTENTE",
            "La transacción de ventanilla no tiene movimiento de caja.",
        )

    if caja["Naturaleza"] != "I":
        return

    totales = caja_repo.calcular_totales(conn, id_jornada)

    if totales is None or saldo_esperado(totales) < decimal(caja["Monto"]):
        raise problema(
            409,
            "EFECTIVO_INSUFICIENTE_EN_CAJA",
            "La caja no tiene efectivo para el reverso.",
        )


def reversar(
    conn: Connection,
    usuario: Usuario,
    id_interno: int | None,
    id_transaccion: int,
    motivo: str,
    ip: str,
    deps: DependenciasOperacion,
) -> Transaccion:
    """Crea el reverso MTI 0400 y sus movimientos contrarios.

    Invierte los movimientos de cuenta, comisiones, asiento contable
    y movimiento de caja cuando corresponde.

    La transacción original conserva sus registros y únicamente
    cambia su estado a Reversada.

    El motivo se registra en la auditoría.
    """
    with auditar(
        "REVERSAR_TRANSACCION",
        "Transacciones.Transaccion",
        usuario,
        ip,
        f"transaccion={id_transaccion} motivo={motivo[:200]}",
    ) as registro:
        deps.verificar_habilitadas()
        supervisor = exigir_id_interno(id_interno)

        with conn.begin():
            original = repo.obtener_transaccion(
                conn,
                id_transaccion,
                bloquear=True,
            )

            if original is None:
                raise transaccion_no_encontrada()

            verificar_alcance(usuario, original)

            if original["Estado"] == "Reversada" or repo.existe_reverso(
                conn,
                id_transaccion,
            ):
                raise problema(
                    409,
                    "TRANSACCION_YA_REVERSADA",
                    "La transacción ya tiene reverso.",
                )

            if (
                original["TipoOperacion"] != "Normal"
                or original["Estado"] != "Completada"
            ):
                raise problema(
                    409,
                    "TRANSACCION_NO_REVERSABLE",
                    "La transacción no se puede reversar.",
                )

            verificar_reverso_soportado(original, supervisor)

            id_jornada = original["IdJornadaCaja"]
            caja = None

            if id_jornada is not None:
                jornada = caja_repo.obtener_jornada(
                    conn,
                    id_jornada,
                    bloquear=True,
                )

                if jornada is None or jornada["Estado"] != "ABIERTA":
                    raise problema(
                        409,
                        "JORNADA_CERRADA",
                        "La jornada ya está cerrada.",
                    )

                if (
                    caja_repo.obtener_cuadre_de_jornada(
                        conn,
                        id_jornada,
                    )
                    is not None
                ):
                    raise problema(
                        409,
                        "JORNADA_EN_CUADRE",
                        "La jornada ya tiene cuadre; no admite operaciones.",
                    )

                caja = repo.movimiento_caja_de_transaccion(
                    conn,
                    id_transaccion,
                )

                verificar_efectivo_del_reverso(conn, id_jornada, caja)

            movimientos = repo.movimientos_de_transaccion(
                conn,
                id_transaccion,
            )

            if not movimientos:
                raise problema(
                    409,
                    "TRANSACCION_NO_REVERSABLE",
                    "La transacción no movió saldos.",
                )

            verificar_cuentas_del_reverso(conn, movimientos)

            fecha_hora = ahora_ecuador()
            id_fecha = fecha_contable(conn, fecha_hora)
            monto = decimal(original["Monto"])

            numeracion = deps.numerar(
                conn,
                original["TipoTransaccion"],
                "Reverso",
            )

            if numeracion.registro_unico is None:
                raise problema(
                    500,
                    "CONFIGURACION_INCOMPLETA",
                    "Falta la numeración del registro único del reverso.",
                )

            id_reverso = repo.insertar_transaccion(
                conn,
                {
                    "numero_comprobante": numeracion.numero_comprobante,
                    "secuencial": numeracion.secuencial,
                    "registro_unico": numeracion.registro_unico,
                    "numero_autorizacion": numeracion.numero_autorizacion,
                    "mti": "0400",
                    "codigo_procesamiento": numeracion.codigo_procesamiento,
                    "stan": numeracion.stan,
                    "rrn": numeracion.rrn,
                    "tipo_operacion": "Reverso",
                    "tipo_transaccion": original["TipoTransaccion"],
                    "id_cuenta": original["IdCuenta"],
                    "id_cuenta_destino": original["IdCuentaDestino"],
                    "id_canal": original["IdCanal"],
                    "id_agencia": original["IdAgencia"],
                    "id_jornada": id_jornada,
                    "id_relacionada": id_transaccion,
                    "monto": monto,
                    "codigo_pais": deps.codigo_pais_origen,
                    "codigo_respuesta": "00",
                    "ip": ip,
                    "estado": "Completada",
                    "creado_por": supervisor,
                    "id_fecha_contable": id_fecha,
                    "fecha_hora": fecha_hora,
                },
            )

            registro.id_registro = str(id_reverso)

            for movimiento in movimientos:
                repo.aplicar_movimiento_cuenta(
                    conn,
                    id_reverso,
                    movimiento["IdCuenta"],
                    _OPUESTO[str(movimiento["TipoMovimiento"]).strip()],
                    movimiento["RolCuenta"],
                    decimal(movimiento["Monto"]),
                    id_fecha,
                )

            deps.revertir_comisiones(
                conn,
                id_transaccion,
                id_reverso,
            )

            id_asiento = deps.contabilizar(
                conn,
                DatosAsiento(
                    id_transaccion=id_reverso,
                    tipo_transaccion=original["TipoTransaccion"],
                    tipo_operacion="Reverso",
                    monto=monto,
                    id_agencia=original["IdAgencia"],
                    id_fecha_contable=id_fecha,
                    id_transaccion_original=id_transaccion,
                ),
            )

            if id_jornada is not None and caja is not None:
                naturaleza = "E" if caja["Naturaleza"] == "I" else "I"

                id_tipo = repo.id_tipo_movimiento_caja(
                    conn,
                    deps.codigo_tipo_movimiento_caja(
                        original["TipoTransaccion"],
                        naturaleza,
                    ),
                )

                if id_tipo is None:
                    raise problema(
                        500,
                        "CONFIGURACION_INCOMPLETA",
                        "Falta configurar el tipo de movimiento de caja.",
                    )

                repo.insertar_movimiento_caja(
                    conn,
                    id_reverso,
                    id_jornada,
                    caja["IdAgencia"],
                    id_tipo,
                    caja["Monto"],
                    # El motivo queda también en una tabla financiera, no solo
                    # en la auditoría best-effort (M-05/M-46)
                    f"Reverso: {motivo}"[:_LARGO_OBSERVACION_CAJA],
                    id_asiento,
                    id_fecha,
                )

            if not repo.marcar_reversada(
                conn,
                id_transaccion,
            ):
                raise problema(
                    409,
                    "TRANSACCION_YA_REVERSADA",
                    "La transacción ya tiene reverso.",
                )

            fila = repo.obtener_transaccion(
                conn,
                id_reverso,
            )

            if fila is None:
                raise RuntimeError("El reverso no se encontró tras registrarlo")

            return _transaccion(fila)
