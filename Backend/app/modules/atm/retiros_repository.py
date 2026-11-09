"""ATM-03 preparatorio: lecturas parametrizadas, sin reservas de efectivo."""

from typing import Any

from sqlalchemy import Connection, text

from app.modules.atm.saldo_repository import buscar_registro


def leer_registro(conn: Connection, registro: str) -> dict[str, Any] | None:
    return buscar_registro(conn, registro)


def leer_gavetas(conn: Connection, id_atm: int) -> list[dict[str, Any]]:
    """Columnas de ATM-13/T-09; validar contra el despliegue antes de habilitar.

    Los locks protegen solo esta lectura preparatoria y se liberan con rollback.
    No equivalen a una reserva ni a evidencia de dispensacion.
    """
    filas = conn.execute(
        text("""
        SELECT g.IdGaveta, g.IdDenominacion, g.CantidadActual, g.Capacidad,
            g.Estado, d.Valor, d.TipoPieza, d.Estado AS EstadoDenominacion
        FROM ATM.Gaveta g WITH (UPDLOCK, HOLDLOCK)
        JOIN Catalogo.Denominacion d ON d.IdDenominacion=g.IdDenominacion
        WHERE g.IdATM=:atm
        ORDER BY g.IdGaveta
    """),
        {"atm": id_atm},
    ).mappings()
    return [dict(fila) for fila in filas]
