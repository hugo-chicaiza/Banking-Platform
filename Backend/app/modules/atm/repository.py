from typing import Any

from sqlalchemy import Connection, text


def obtener_atm(
    conn: Connection,
    codigo_atm: str,
) -> dict[str, Any] | None:
    """Obtiene un terminal ATM junto con la configuración de su canal."""

    sql = text("""
        SELECT
            a.IdATM AS id_atm,
            a.CodigoATM AS codigo_atm,
            a.TipoTerminal AS tipo_terminal,
            a.Estado AS estado_atm,
            c.IdCanal AS id_canal,
            c.CodigoCanal AS codigo_canal,
            c.Estado AS estado_canal,
            c.RequiereTarjeta AS requiere_tarjeta,
            c.RequierePin AS requiere_pin,
            c.RequiereTerminal AS requiere_terminal
        FROM ATM.ATM AS a
        INNER JOIN Canal.Canal AS c
            ON a.IdCanal = c.IdCanal
        WHERE a.CodigoATM = :codigo_atm
    """)

    fila = conn.execute(
        sql,
        {"codigo_atm": codigo_atm},
    ).mappings().first()

    return dict(fila) if fila is not None else None