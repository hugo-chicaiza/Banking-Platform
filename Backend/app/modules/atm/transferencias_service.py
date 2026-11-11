"""ATM-05 parcial: barrera financiera y prevalidacion interna de solo lectura.

No hay escritor financiero ni camino de exito HTTP. La prevalidacion revierte su
transaccion y no sustituye autorizacion/contabilizacion en la futura confirmacion.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, NoReturn

from sqlalchemy import Connection

from app.core.api.errors import problema
from app.core.database.session_scope import ERRORES_SQL, sesion_sql_acotada
from app.modules.atm import repository, saldo_repository, service, session
from app.modules.atm import transferencias_repository as repo
from app.modules.atm.schemas import AtmTransferenciaRequest
from app.modules.atm.session import SesionATM
from app.modules.atm.terminal_auth import TerminalAutenticado, revalidar_terminal
from app.modules.cuentas.schemas import ID_MONEDA_USD
from app.modules.transacciones.dependencias import DependenciasOperacion
from app.modules.transacciones.repository import autorizar_operacion


def no_habilitada():
    return problema(
        501,
        "OPERACION_NO_HABILITADA",
        "La operación aún no está habilitada en este ambiente.",
    )


def _no_disponible():
    return problema(
        503, "TRANSFERENCIA_NO_DISPONIBLE", "No se pudo comprobar la operación."
    )


def exigir_origen_autorizado(sesion: SesionATM, cuenta: int) -> None:
    if cuenta not in sesion.cuentas:
        raise problema(404, "CUENTA_NO_ENCONTRADA", "La cuenta no está disponible.")


def solicitar_transferencia(
    sesion: SesionATM,
    terminal: TerminalAutenticado,
    entrada: AtmTransferenciaRequest,
    dependencias: DependenciasOperacion,
) -> NoReturn:
    """Barrera antes de abrir CooperativaDB, aun si otro modulo configura sus deps.

    AC-01 se conecta mediante el contrato compartido DependenciasOperacion.
    Configurarlo NO habilita implicitamente ATM-05: faltan contrato del par,
    comisiones, numeracion y comprobante. No invocar escritores hasta resolverlo.
    """
    revalidar_terminal(terminal)
    exigir_origen_autorizado(sesion, entrada.id_cuenta_origen)
    dependencias.verificar_habilitadas()
    raise no_habilitada()


@dataclass(frozen=True, repr=False)
class PreparacionTransferencia:
    id_origen: int
    id_destino: int
    monto: Decimal
    comision_calculada: Decimal
    id_moneda: int
    id_transaccion_candidata: int | None


def _decimal(valor: object) -> Decimal:
    try:
        resultado = Decimal(str(valor))
        if not resultado.is_finite() or resultado < 0:
            raise ValueError
        return resultado
    except (ValueError, InvalidOperation):
        raise _no_disponible() from None


def validar_reutilizacion(
    anterior: dict[str, Any] | None,
    sesion: SesionATM,
    entrada: AtmTransferenciaRequest,
    destino: int,
    canal: int,
) -> int | None:
    """Huella de la enviada, NO comprobante ni prueba de integridad del par.

    El formato/clave de la recibida y el replay exacto siguen pendientes.
    Nunca devolver exito solo porque se encontro una enviada compatible.
    """
    if anterior is None:
        return None
    if not (
        anterior["TipoOperacion"] == "Normal"
        and anterior["TipoTransaccion"] == "Transferencia_Enviada"
        and anterior["IdCuenta"] == entrada.id_cuenta_origen
        and anterior["IdCuentaDestino"] == destino
        and anterior["IdTarjeta"] == sesion.id_tarjeta
        and anterior["IdATM"] == sesion.id_atm
        and anterior["IdCanal"] == canal
        and _decimal(anterior["Monto"]) == entrada.monto
    ):
        raise problema(
            409,
            "REGISTRO_UNICO_REUTILIZADO",
            "El registroUnico ya se usó en otra operación.",
        )
    return int(anterior["IdTransaccion"])


def prevalidar_transferencia(
    conn: Connection,
    sesion: SesionATM,
    terminal: TerminalAutenticado,
    entrada: AtmTransferenciaRequest,
) -> PreparacionTransferencia:
    """Componente interno preparatorio, NO conectado a una ruta financiera activa.

    Las lecturas se revierten incluso en exito. Sus resultados no se pueden
    reutilizar para escribir luego: se deben revalidar dentro de la confirmacion.
    """
    exigir_origen_autorizado(sesion, entrada.id_cuenta_origen)
    revalidar_terminal(terminal)
    try:
        with sesion_sql_acotada(conn):
            tx = conn.begin()
            try:
                return _prevalidar(conn, sesion, terminal, entrada)
            finally:
                tx.rollback()
    except ERRORES_SQL:
        raise _no_disponible() from None


def _prevalidar(
    conn: Connection,
    sesion: SesionATM,
    terminal: TerminalAutenticado,
    entrada: AtmTransferenciaRequest,
) -> PreparacionTransferencia:
    # Mismo orden relativo que ATM-02: registro, terminal, tarjeta y cuentas.
    anterior = repo.leer_registro(conn, entrada.registro_unico)
    saldo_repository.bloquear_contexto(conn, sesion.id_atm, sesion.id_tarjeta)
    atm = service.validar_terminal(conn, terminal.codigo_atm)
    if atm["id_atm"] != sesion.id_atm:
        raise problema(403, "TERMINAL_NO_AUTORIZADO", "El terminal no permite operar.")
    tarjeta = repository.obtener_tarjeta(conn, sesion.id_tarjeta)
    if tarjeta is None or tarjeta["id_cuenta"] != entrada.id_cuenta_origen:
        raise problema(404, "CUENTA_NO_ENCONTRADA", "La cuenta no está disponible.")
    if tarjeta["estado_tarjeta"] != "Activa" or not tarjeta["pin_asignado"]:
        raise problema(403, "TARJETA_NO_ACTIVA", "La tarjeta no permite operar.")
    # Releer revocacion/version tras adquirir los locks comunes, tambien en replay.
    session.require_sesion_operativa(
        session.require_sesion_pin_actual(session.require_sesion_atm(sesion))
    )
    destino = repo.resolver_destino(
        conn, entrada.numero_cuenta_destino.get_secret_value()
    )
    if destino is None:
        raise problema(
            404, "CUENTA_DESTINO_NO_ENCONTRADA", "La cuenta destino no está disponible."
        )
    if destino == entrada.id_cuenta_origen:
        raise problema(
            422,
            "CUENTA_DESTINO_IGUAL_ORIGEN",
            "La cuenta destino debe ser distinta del origen.",
        )
    repo.bloquear_cuentas(conn, entrada.id_cuenta_origen, destino)
    if (
        repo.resolver_destino(conn, entrada.numero_cuenta_destino.get_secret_value())
        != destino
    ):
        raise problema(
            404, "CUENTA_DESTINO_NO_ENCONTRADA", "La cuenta destino no está disponible."
        )
    origen = saldo_repository.leer_cuenta(conn, entrada.id_cuenta_origen)
    receptora = saldo_repository.leer_cuenta(conn, destino)
    if origen is None:
        raise problema(404, "CUENTA_NO_ENCONTRADA", "La cuenta no está disponible.")
    if receptora is None or receptora["Estado"] != "Activa":
        raise problema(
            404, "CUENTA_DESTINO_NO_ENCONTRADA", "La cuenta destino no está disponible."
        )
    if origen["Estado"] != "Activa":
        raise problema(409, "CUENTA_NO_ACTIVA", "La cuenta no está activa.")
    ahora = origen["Ahora"]
    if not isinstance(ahora, datetime):
        raise _no_disponible()
    expiracion = tarjeta.get("fecha_expiracion")
    if isinstance(expiracion, datetime):
        expiracion = expiracion.date()
    if expiracion is None or expiracion < ahora.date():
        raise problema(403, "TARJETA_NO_ACTIVA", "La tarjeta no permite operar.")
    candidato = validar_reutilizacion(
        anterior, sesion, entrada, destino, atm["id_canal"]
    )
    autorizacion = autorizar_operacion(
        conn,
        entrada.id_cuenta_origen,
        atm["id_canal"],
        "Transferencia_Enviada",
        entrada.monto,
        fecha_hora=ahora,
    )
    codigo = autorizacion.get("CodigoRespuesta")
    if codigo == "51":
        raise problema(
            422, "FONDOS_INSUFICIENTES", "El disponible no cubre monto y comisión."
        )
    if codigo in {"05", "61", "65"}:
        # 05 incluye restricciones; 61 diario/mensual/maximo. No inventar un mapeo.
        raise no_habilitada()
    if codigo != "00":
        raise _no_disponible()
    comision = _decimal(autorizacion.get("Comision"))
    disponible = _decimal(origen["Saldo"]) - _decimal(origen["SaldoRetenido"])
    if disponible < entrada.monto + comision:
        raise problema(
            422, "FONDOS_INSUFICIENTES", "El disponible no cubre monto y comisión."
        )
    return PreparacionTransferencia(
        entrada.id_cuenta_origen,
        destino,
        entrada.monto,
        comision,
        ID_MONEDA_USD,
        candidato,
    )
