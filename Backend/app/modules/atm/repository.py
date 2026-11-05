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

    fila = (
        conn.execute(
            sql,
            {"codigo_atm": codigo_atm},
        )
        .mappings()
        .first()
    )

    return dict(fila) if fila is not None else None


def obtener_tarjeta(
    conn: Connection,
    id_tarjeta: int,
) -> dict[str, Any] | None:
    """Obtiene los datos necesarios para validar una tarjeta."""

    sql = text("""
        SELECT
            t.IdTarjeta AS id_tarjeta,
            t.IdCliente AS id_cliente,
            t.IdCuenta AS id_cuenta,
            t.NombresTitular AS nombres_titular,
            t.ApellidosTitular AS apellidos_titular,
            t.PinAsignado AS pin_asignado,
            t.FechaExpiracion AS fecha_expiracion,
            t.Estado AS estado_tarjeta
        FROM Tarjeta.Tarjeta AS t
        WHERE t.IdTarjeta = :id_tarjeta
    """)

    fila = (
        conn.execute(
            sql,
            {"id_tarjeta": id_tarjeta},
        )
        .mappings()
        .first()
    )

    return dict(fila) if fila is not None else None
