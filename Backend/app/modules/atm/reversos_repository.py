"""Lecturas preparatorias ATM-08; reutiliza locks y deteccion de TRX-03."""

from sqlalchemy import Connection, text

from app.modules.transacciones import repository as trx


def leer_original(conn: Connection, identificador: int) -> trx.Fila | None:
    return trx.obtener_transaccion(conn, identificador, bloquear=True)


def tiene_reverso(conn: Connection, identificador: int) -> bool:
    return trx.existe_reverso(conn, identificador)


def leer_registro(conn: Connection, registro: str) -> trx.Fila | None:
    """Futuro registro de reverso: su provision no esta definida por ATM-08.

    Encontrar una fila no autoriza replay: motivo y resultado financiero/efectivo
    requieren un contrato adicional. No genera claves ni escribe reservas.
    """
    fila = (
        conn.execute(
            text("""
            SELECT IdTransaccion, RegistroUnico, IdTransaccionRelacionada,
                TipoOperacion, IdCuenta, IdATM, IdTarjeta, Estado, MTI
            FROM Transacciones.Transaccion WITH (UPDLOCK, HOLDLOCK)
            WHERE RegistroUnico=:registro
        """),
            {"registro": registro},
        )
        .mappings()
        .one_or_none()
    )
    return dict(fila) if fila is not None else None
