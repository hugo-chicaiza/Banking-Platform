"""Auditoría de las operaciones de dinero del ATM (E0-05 B), lista para cuando se activen.

Las rutas de retiro, transferencia, reverso y depósito responden hoy «no habilitada».
Al activarlas, cada operación llama `confirmar_atm(...)` **dentro de su transacción**,
justo antes de confirmarla: el evento queda en la bandeja junto con la transacción
(o ninguno de los dos) y apunta a `Transacciones.Transaccion` con sus montos. La
prueba `test_auditoria_dinero.py` exige esa llamada en cuanto un servicio deje de
responder «no habilitada».
"""

from typing import Any, Literal

from sqlalchemy import Connection

from app.core.security.operador import encolar_evento
from app.modules.atm.session import SesionATM
from app.modules.atm.terminal_auth import TerminalAutenticado

OperacionATM = Literal["retiro", "transferencia", "reverso", "deposito"]

# Códigos del catálogo Auditoria.TipoEvento (migración 202611191400)
_EVENTO_ATM: dict[str, str] = {
    "retiro": "ATM_RETIRO",
    "transferencia": "ATM_TRANSFERENCIA",
    "reverso": "ATM_REVERSO",
    "deposito": "ATM_DEPOSITO",
}


def confirmar_atm(
    conn: Connection,
    operacion: OperacionATM,
    sesion: SesionATM,
    terminal: TerminalAutenticado,
    id_transaccion: int,
    *,
    origen: str = "",
    cambios: dict[str, Any] | None = None,
) -> None:
    """Evento de éxito de una operación de dinero del ATM en la bandeja, dentro de la
    transacción. Sin PAN, PIN ni números de cuenta: solo ids internos y montos."""
    encolar_evento(
        conn,
        codigo=_EVENTO_ATM[operacion],
        sujeto=f"atm:{terminal.codigo_atm}",
        organizacion=None,
        roles=[],
        agencia=None,
        sesion=sesion.jti,
        origen=origen,
        canal="ATM",
        tabla="Transacciones.Transaccion",
        id_objetivo=str(id_transaccion),
        descripcion=f"atm={terminal.codigo_atm} operacion={operacion} tarjeta={sesion.id_tarjeta}",
        cambios={"idAtm": sesion.id_atm, **(cambios or {})},
    )
