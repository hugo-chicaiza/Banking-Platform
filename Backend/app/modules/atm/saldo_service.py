"""Consulta gratuita: comprobante persistente y saldos actuales en cada reintento."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy import Connection

from app.core.api.errors import problema
from app.core.database.session_scope import ERRORES_SQL, sesion_sql_acotada
from app.modules.atm import repository, service
from app.modules.atm import saldo_repository as repo
from app.modules.atm.schemas import AtmSaldoRequest, AtmSaldoResponse
from app.modules.atm.session import SesionATM
from app.modules.atm.terminal_auth import TerminalAutenticado, revalidar_terminal
from app.modules.transacciones import numeracion
from app.modules.transacciones.repository import autorizar_operacion, comision_de

_EC = timezone(timedelta(hours=-5))


def _no_disponible() -> HTTPException:
    return problema(
        503,
        "CONSULTA_SALDO_NO_DISPONIBLE",
        "No se pudo confirmar la consulta. Reintente con el mismo registroUnico.",
    )


def _dinero(valor: object) -> Decimal:
    try:
        resultado = Decimal(str(valor))
        if not resultado.is_finite():
            raise ValueError
        return resultado
    except (InvalidOperation, ValueError):
        raise _no_disponible() from None


def _fecha(valor: object) -> datetime:
    if not isinstance(valor, datetime):
        raise _no_disponible()
    return valor.replace(tzinfo=_EC) if valor.tzinfo is None else valor.astimezone(_EC)


def consultar_saldo(
    conn: Connection,
    sesion: SesionATM,
    terminal: TerminalAutenticado,
    entrada: AtmSaldoRequest,
    ip: str | None,
) -> AtmSaldoResponse:
    if entrada.id_cuenta not in sesion.cuentas:
        raise problema(404, "CUENTA_NO_ENCONTRADA", "La cuenta no está disponible.")
    revalidar_terminal(terminal)
    rechazo = False
    try:
        with sesion_sql_acotada(conn), conn.begin():
            if not numeracion.bloquear_numeracion(conn):
                raise _no_disponible()
            anterior = repo.buscar_registro(conn, entrada.registro_unico)
            repo.bloquear_contexto(conn, sesion.id_atm, sesion.id_tarjeta)
            atm = service.validar_terminal(conn, terminal.codigo_atm)
            if atm["id_atm"] != sesion.id_atm:
                raise problema(
                    403, "TERMINAL_NO_AUTORIZADO", "El terminal no permite operar."
                )
            tarjeta = repository.obtener_tarjeta(conn, sesion.id_tarjeta)
            cuenta = repo.leer_cuenta(conn, entrada.id_cuenta)
            if (
                tarjeta is None
                or cuenta is None
                or tarjeta["id_cuenta"] != entrada.id_cuenta
            ):
                raise problema(
                    404, "CUENTA_NO_ENCONTRADA", "La cuenta no está disponible."
                )
            ahora = _fecha(cuenta["Ahora"])
            vencimiento = tarjeta.get("fecha_expiracion")
            if isinstance(vencimiento, datetime):
                vencimiento = vencimiento.date()
            if (
                tarjeta["estado_tarjeta"] != "Activa"
                or not tarjeta["pin_asignado"]
                or vencimiento is None
                or vencimiento < ahora.date()
            ):
                raise problema(
                    403, "TARJETA_NO_ACTIVA", "La tarjeta no permite operar."
                )
            tipo = cuenta["TipoCuenta"]
            if tipo not in ("Ahorro", "Corriente"):
                raise problema(
                    403,
                    "TIPO_CUENTA_NO_PERMITIDO",
                    "La cuenta no permite consultas ATM.",
                )
            procesamiento = numeracion.CODIGOS_CONSULTA[tipo]
            saldo, retenido = _dinero(cuenta["Saldo"]), _dinero(cuenta["SaldoRetenido"])
            if retenido < 0:
                raise _no_disponible()
            if anterior is not None:
                if not (
                    anterior["TipoTransaccion"] == "Consulta"
                    and anterior["TipoOperacion"] == "Normal"
                    and anterior["MTI"] == "0200"
                    and anterior["IdCuenta"] == entrada.id_cuenta
                    and anterior["IdTarjeta"] == sesion.id_tarjeta
                    and anterior["IdATM"] == sesion.id_atm
                    and anterior["IdCanal"] == atm["id_canal"]
                    and anterior["CodigoProcesamiento"] == procesamiento
                    and _dinero(anterior["Monto"]) == 0
                ):
                    raise problema(
                        409,
                        "REGISTRO_UNICO_REUTILIZADO",
                        "El registroUnico ya se usó en otra operación.",
                    )
                if _dinero(comision_de(conn, anterior["IdTransaccion"])) != 0:
                    raise problema(
                        409,
                        "REGISTRO_UNICO_REUTILIZADO",
                        "El registroUnico no corresponde a una consulta gratuita.",
                    )
                if (anterior["Estado"], anterior["CodigoRespuesta"]) not in (
                    ("Completada", "00"),
                    ("Rechazada", "05"),
                ):
                    raise problema(
                        409,
                        "OPERACION_NO_COMPLETADA",
                        "La operación requiere revisión.",
                    )
                rechazo = (
                    anterior["Estado"] == "Rechazada" or cuenta["Estado"] != "Activa"
                )
                id_transaccion = anterior["IdTransaccion"]
                comprobante = anterior["NumeroComprobante"]
                fecha_original = _fecha(anterior["FechaHoraSistema"])
            else:
                autorizacion = autorizar_operacion(
                    conn,
                    entrada.id_cuenta,
                    atm["id_canal"],
                    "Consulta",
                    Decimal(0),
                    fecha_hora=ahora.replace(tzinfo=None),
                )
                if autorizacion.get("CodigoRespuesta") not in ("00", "05"):
                    raise _no_disponible()
                if _dinero(autorizacion.get("Comision")) != 0:
                    # No cobrar ni ignorar una tarifa incompatible con la consulta gratuita.
                    raise _no_disponible()
                rechazo = (
                    cuenta["Estado"] != "Activa"
                    or autorizacion["CodigoRespuesta"] == "05"
                )
                ids = numeracion.numerar_consulta(conn, ahora, tipo)
                contable = repo.fecha_contable(conn, ahora.replace(tzinfo=None))
                if type(contable) is not int or contable <= 0:
                    raise _no_disponible()
                comprobante = ids.numero_comprobante
                fecha_original = ahora
                id_transaccion = repo.insertar_consulta(
                    conn,
                    {
                        "comprobante": comprobante,
                        "secuencial": ids.secuencial,
                        "registro": entrada.registro_unico,
                        "procesamiento": ids.codigo_procesamiento,
                        "stan": ids.stan,
                        "rrn": ids.rrn,
                        "cuenta": entrada.id_cuenta,
                        "tarjeta": sesion.id_tarjeta,
                        "atm": sesion.id_atm,
                        "canal": atm["id_canal"],
                        "agencia": cuenta["IdAgencia"],
                        "ahora": ahora.replace(tzinfo=None),
                        "usuario": terminal.audit_user_id,
                        "fecha_contable": contable,
                        "ip": ip,
                        "respuesta": "05" if rechazo else "00",
                        "estado": "Rechazada" if rechazo else "Completada",
                    },
                )
            # Una revocación de credencial detectada aquí cancela también la inserción.
            revalidar_terminal(terminal)
            respuesta = AtmSaldoResponse(
                id_transaccion=id_transaccion,
                numero_comprobante=comprobante,
                comision=Decimal(0),
                saldo_contable=saldo,
                saldo_retenido=retenido,
                saldo_disponible=saldo - retenido,
                fecha_hora_sistema=fecha_original,
                fecha_consulta_saldo=ahora,
                es_reintento=anterior is not None,
            )
        # Rechazos de negocio se comunican DESPUÉS del commit para conservar el registro.
    except (*ERRORES_SQL, RuntimeError):
        raise _no_disponible() from None
    if rechazo:
        raise problema(409, "OPERACION_RECHAZADA", "La consulta fue rechazada.")
    return respuesta
