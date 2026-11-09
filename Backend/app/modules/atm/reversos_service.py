"""ATM-08 parcial: sin escrituras financieras ni simulacion de efectivo."""

from dataclasses import dataclass
from datetime import datetime
from typing import NoReturn

from sqlalchemy import Connection

from app.core.api.errors import problema
from app.core.database.session_scope import ERRORES_SQL, sesion_sql_acotada
from app.modules.atm import repository, saldo_repository, service, session
from app.modules.atm import reversos_repository as repo
from app.modules.atm.schemas import AtmReversoRequest
from app.modules.atm.session import SesionATM
from app.modules.atm.terminal_auth import TerminalAutenticado, revalidar_terminal
from app.modules.transacciones import repository as trx
from app.modules.transacciones.dependencias import DependenciasOperacion


def no_habilitada():
    return problema(
        501,
        "OPERACION_NO_HABILITADA",
        "La operación aún no está habilitada en este ambiente.",
    )


def _no_reversable():
    return problema(
        409, "TRANSACCION_NO_REVERSABLE", "La transacción no se puede reversar."
    )


def _no_disponible():
    return problema(503, "REVERSO_NO_DISPONIBLE", "No se pudo comprobar la operación.")


def solicitar_reverso(
    sesion: SesionATM,
    terminal: TerminalAutenticado,
    entrada: AtmReversoRequest,
    dependencias: DependenciasOperacion,
) -> NoReturn:
    """No abrir CooperativaDB ni invocar TRX-03.reversar o escritores.

    Configurar deps genericas no habilita ATM-08: faltan G-06/AC-01,
    idempotencia del contrato y evidencia/reglas de dispensacion.
    """
    revalidar_terminal(terminal)
    dependencias.verificar_habilitadas()
    raise no_habilitada()


@dataclass(frozen=True, repr=False)
class PreparacionReverso:
    id_original: int
    id_cuenta: int


def validar_original(original: trx.Fila | None, sesion: SesionATM) -> trx.Fila:
    # No revelar estado de operaciones ajenas. La HU define 409 para otra cuenta.
    if original is None or original["IdCuenta"] not in sesion.cuentas:
        raise _no_reversable()
    return original


def prevalidar_reverso(
    conn: Connection,
    sesion: SesionATM,
    terminal: TerminalAutenticado,
    entrada: AtmReversoRequest,
) -> PreparacionReverso:
    """Preparacion interna de lectura, siempre rollback, no conectada a HTTP.

    No garantiza que se pueda devolver efectivo/comision ni autoriza escrituras.
    Una futura confirmacion debe revalidar dentro de su transaccion financiera.
    """
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


def _prevalidar(conn, sesion, terminal, entrada) -> PreparacionReverso:
    original = validar_original(
        repo.leer_original(conn, entrada.id_transaccion), sesion
    )
    saldo_repository.bloquear_contexto(conn, sesion.id_atm, sesion.id_tarjeta)
    atm = service.validar_terminal(conn, terminal.codigo_atm)
    if atm["id_atm"] != sesion.id_atm:
        raise problema(403, "TERMINAL_NO_AUTORIZADO", "El terminal no permite operar.")
    tarjeta = repository.obtener_tarjeta(conn, sesion.id_tarjeta)
    if tarjeta is None or tarjeta["id_cuenta"] != original["IdCuenta"]:
        raise _no_reversable()
    session.require_sesion_operativa(
        session.require_sesion_pin_actual(session.require_sesion_atm(sesion))
    )
    cuenta = saldo_repository.leer_cuenta(conn, original["IdCuenta"])
    if cuenta is None:
        raise _no_reversable()
    ahora = cuenta["Ahora"]
    if not isinstance(ahora, datetime):
        raise _no_disponible()
    vencimiento = tarjeta.get("fecha_expiracion")
    if isinstance(vencimiento, datetime):
        vencimiento = vencimiento.date()
    if (
        tarjeta["estado_tarjeta"] != "Activa"
        or not tarjeta["pin_asignado"]
        or vencimiento is None
        or vencimiento < ahora.date()
    ):
        raise problema(403, "TARJETA_NO_ACTIVA", "La tarjeta no permite operar.")
    if original["Estado"] == "Reversada" or repo.tiene_reverso(
        conn, entrada.id_transaccion
    ):
        raise problema(
            409, "TRANSACCION_YA_REVERSADA", "La transacción ya tiene reverso."
        )
    if original["TipoOperacion"] != "Normal" or original["Estado"] != "Completada":
        raise _no_reversable()
    # Como TRX-03: una consulta sin movimientos no es un reverso financiero.
    if not trx.movimientos_de_transaccion(conn, entrada.id_transaccion):
        raise _no_reversable()
    return PreparacionReverso(entrada.id_transaccion, original["IdCuenta"])
