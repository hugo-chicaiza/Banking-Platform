"""Preparacion ATM-05: solo lecturas parametrizadas y bloqueos; sin INSERT/UPDATE.

No asigna numeracion ni guarda un registro como sustituto de una transferencia.
"""

from typing import Any

from sqlalchemy import Connection, text


def resolver_destino(conn: Connection, numero: str) -> int | None:
    return conn.scalar(
        text("SELECT IdCuenta FROM Cuentas.Cuenta WHERE NumeroCuenta=:numero"),
        {"numero": numero},
    )


def bloquear_cuentas(conn: Connection, origen: int, destino: int) -> None:
    # Dos SELECT individuales: ORDER BY en una consulta no fija el orden de locks.
    for cuenta in sorted({origen, destino}):
        conn.execute(
            text(
                "SELECT IdCuenta FROM Cuentas.Cuenta WITH (UPDLOCK, HOLDLOCK) WHERE IdCuenta=:id"
            ),
            {"id": cuenta},
        ).all()


def leer_registro(conn: Connection, registro: str) -> dict[str, Any] | None:
    fila = (
        conn.execute(
            text("""
        SELECT IdTransaccion, NumeroComprobante, RegistroUnico, MTI,
            TipoTransaccion, TipoOperacion, IdCuenta, IdCuentaDestino,
            IdTarjeta, IdATM, IdCanal, Monto, Estado, IdTransaccionRelacionada
        FROM Transacciones.Transaccion WITH (UPDLOCK, HOLDLOCK)
        WHERE RegistroUnico=:registro;
    """),
            {"registro": registro},
        )
        .mappings()
        .one_or_none()
    )
    return dict(fila) if fila is not None else None
