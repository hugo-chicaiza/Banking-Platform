from typing import Any

from sqlalchemy import Connection, text


def _rows(
    conn: Connection, sql: str, params: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(text(sql), params or {}).mappings()]


def _one(
    conn: Connection, sql: str, params: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    rows = _rows(conn, sql, params)
    return rows[0] if rows else None


# Validar cliente, riesgo, producto y agencia.


def obtener_cliente(conn: Connection, id_cliente: int) -> dict[str, Any] | None:
    """Devuelve {estado} del cliente o None si no existe."""
    return _one(
        conn,
        """
        SELECT Estado AS estado
        FROM Clientes.Cliente
        WHERE IdCliente = :id_cliente
        """,
        {"id_cliente": id_cliente},
    )


def obtener_riesgo_vigente(conn: Connection, id_cliente: int) -> dict[str, Any] | None:
    """Devuelve el riesgo vigente más reciente del cliente.

    Columnas: estado ('Aprobado' | 'Rechazado' | ...).
    """
    return _one(
        conn,
        """
        SELECT TOP 1 Estado AS estado
        FROM Clientes.RiesgoCliente
        WHERE IdCliente = :id_cliente
          AND Vigente = 1
        ORDER BY FechaEvaluacion DESC
        """,
        {"id_cliente": id_cliente},
    )


def obtener_producto(conn: Connection, id_producto: int) -> dict[str, Any] | None:
    """Devuelve {tipo_producto, estado, monto_apertura_minimo} o None."""
    return _one(
        conn,
        """
        SELECT TipoProducto      AS tipo_producto,
               Estado            AS estado,
               MontoAperturaMinimo AS monto_apertura_minimo
        FROM ProductosFinancieros.Producto
        WHERE IdProducto = :id_producto
        """,
        {"id_producto": id_producto},
    )


def obtener_agencia(conn: Connection, id_agencia: str) -> dict[str, Any] | None:
    """Devuelve {estado} de la agencia o None si no existe."""
    return _one(
        conn,
        """
        SELECT Estado AS estado
        FROM Organizacion.Agencia
        WHERE Codigo = :id_agencia
        """,
        {"id_agencia": id_agencia},
    )


# Apertura de la cuenta


def abrir_cuenta(
    conn: Connection,
    numero_cuenta: str,
    id_cliente: int,
    id_producto: int,
    id_agencia: str,
    tipo_cuenta: str,
    id_moneda: int,
    creado_por: str,
) -> dict[str, Any]:
    """Llama a Cuentas.usp_AbrirCuenta y devuelve la cuenta creada.

    El SP valida  y devuelve una fila con los datos de la cuenta recién abierta.
    """
    conn.execute(
        text(
            """
            EXEC Cuentas.usp_AbrirCuenta
                @NumeroCuenta     = :numero_cuenta,
                @IdCliente        = :id_cliente,
                @IdProducto       = :id_producto,
                @IdAgencia        = :id_agencia,
                @TipoCuenta       = :tipo_cuenta,
                @IdMoneda         = :id_moneda,
                @CreadoPor        = :creado_por
            """
        ),
        {
            "numero_cuenta": numero_cuenta,
            "id_cliente": id_cliente,
            "id_producto": id_producto,
            "id_agencia": id_agencia,
            "tipo_cuenta": tipo_cuenta,
            "id_moneda": id_moneda,
            "creado_por": creado_por,
        },
    )

    # Lectura de la cuenta recién creada por número (único e inmutable tras apertura)
    cuenta = _one(
        conn,
        """
        SELECT IdCuenta        AS id_cuenta,
               NumeroCuenta    AS numero_cuenta,
               IdCliente       AS id_cliente,
               IdProducto      AS id_producto,
               IdAgencia       AS id_agencia,
               TipoCuenta      AS tipo_cuenta,
               IdMoneda        AS id_moneda,
               Saldo           AS saldo,
               SaldoRetenido   AS saldo_retenido,
               Estado          AS estado
        FROM Cuentas.Cuenta
        WHERE NumeroCuenta = :numero_cuenta
        """,
        {"numero_cuenta": numero_cuenta},
    )

    if cuenta is None:  # pragma: no cover
        raise RuntimeError("usp_AbrirCuenta no devolvió la cuenta creada")

    return cuenta
