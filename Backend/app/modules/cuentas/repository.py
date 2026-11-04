from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, text

_ESTADOS_CUENTA_BD = {
    "ACTIVA": "Activa",
    "INACTIVA": "Inactiva",
    "BLOQUEADA": "Bloqueada",
    "CERRADA": "Cerrada",
}
_ESTADOS_CUENTA_API = {valor: clave for clave, valor in _ESTADOS_CUENTA_BD.items()}


def _cuenta_desde_bd(fila: dict[str, Any]) -> dict[str, Any]:
    """Adapta los estados verificados sin alterar el contrato ni la fila leída."""
    return {
        **fila,
        "estado": _ESTADOS_CUENTA_API.get(fila["estado"], fila["estado"]),
    }


def _rows(
    conn: Connection, sql: str, params: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(text(sql), params or {}).mappings()]


def _one(
    conn: Connection, sql: str, params: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    rows = _rows(conn, sql, params)
    return rows[0] if rows else None


def consultar_cuentas(
    conn: Connection,
    *,
    id_cliente: int | None = None,
    numero_cuenta: str | None = None,
    estado: str | None = None,
    id_agencia: str | None = None,
    page: int = 1,
    page_size: int = 20,
    campo: str = "IdCuenta",
    direccion: str = "asc",
) -> tuple[list[dict[str, Any]], int]:
    """Una lectura conserva el total incluso cuando la página está vacía."""
    filas = _rows(
        conn,
        """
        WITH Filtrados AS (
            SELECT c.IdCuenta AS id_cuenta, c.NumeroCuenta AS numero_cuenta,
                   c.IdCliente AS id_cliente, c.IdProducto AS id_producto,
                   c.IdAgencia AS id_agencia, p.TipoCuenta AS tipo_cuenta,
                   c.Estado AS estado,
                   ROW_NUMBER() OVER (ORDER BY
                       CASE WHEN :campo = 'IdCuenta' AND :direccion = 'asc'
                            THEN c.IdCuenta END ASC,
                       CASE WHEN :campo = 'IdCuenta' AND :direccion = 'desc'
                            THEN c.IdCuenta END DESC,
                       CASE WHEN :campo = 'NumeroCuenta' AND :direccion = 'asc'
                            THEN c.NumeroCuenta END ASC,
                       CASE WHEN :campo = 'NumeroCuenta' AND :direccion = 'desc'
                            THEN c.NumeroCuenta END DESC,
                       CASE WHEN :campo = 'IdCliente' AND :direccion = 'asc'
                            THEN c.IdCliente END ASC,
                       CASE WHEN :campo = 'IdCliente' AND :direccion = 'desc'
                            THEN c.IdCliente END DESC,
                       CASE WHEN :campo = 'IdProducto' AND :direccion = 'asc'
                            THEN c.IdProducto END ASC,
                       CASE WHEN :campo = 'IdProducto' AND :direccion = 'desc'
                            THEN c.IdProducto END DESC,
                       CASE WHEN :campo = 'IdAgencia' AND :direccion = 'asc'
                            THEN c.IdAgencia END ASC,
                       CASE WHEN :campo = 'IdAgencia' AND :direccion = 'desc'
                            THEN c.IdAgencia END DESC,
                       CASE WHEN :campo = 'TipoCuenta' AND :direccion = 'asc'
                            THEN p.TipoCuenta END ASC,
                       CASE WHEN :campo = 'TipoCuenta' AND :direccion = 'desc'
                            THEN p.TipoCuenta END DESC,
                       CASE WHEN :campo = 'Estado' AND :direccion = 'asc'
                            THEN c.Estado END ASC,
                       CASE WHEN :campo = 'Estado' AND :direccion = 'desc'
                            THEN c.Estado END DESC,
                       c.IdCuenta ASC
                   ) AS numero_fila
            FROM Cuentas.Cuenta AS c
            INNER JOIN ProductosFinancieros.Producto AS p
              ON p.IdProducto = c.IdProducto
            WHERE (:id_cliente IS NULL OR c.IdCliente = :id_cliente)
              AND (:numero_cuenta IS NULL OR c.NumeroCuenta = :numero_cuenta)
              AND (:estado IS NULL OR c.Estado = :estado)
              AND (:id_agencia IS NULL OR c.IdAgencia = :id_agencia)
        )
        SELECT p.*, t.total
        FROM (SELECT COUNT(*) AS total FROM Filtrados) AS t
        LEFT JOIN Filtrados AS p
          ON p.numero_fila > :offset AND p.numero_fila <= :limite
        ORDER BY p.numero_fila
        """,
        {
            "id_cliente": id_cliente,
            "numero_cuenta": numero_cuenta,
            "estado": _ESTADOS_CUENTA_BD.get(estado, estado)
            if estado is not None
            else None,
            "id_agencia": id_agencia,
            "campo": campo,
            "direccion": direccion,
            "offset": (page - 1) * page_size,
            "limite": page * page_size,
        },
    )
    total = int(filas[0]["total"]) if filas else 0
    return [
        _cuenta_desde_bd(fila) for fila in filas if fila["id_cuenta"] is not None
    ], total


def obtener_cuenta_por_id(conn: Connection, id_cuenta: int) -> dict[str, Any] | None:
    """Lee la cuenta; la moneda global USD se completa en el servicio."""
    fila = _one(
        conn,
        """
        SELECT c.IdCuenta AS id_cuenta, c.NumeroCuenta AS numero_cuenta,
               c.IdCliente AS id_cliente, c.IdProducto AS id_producto,
               c.IdAgencia AS id_agencia, p.TipoCuenta AS tipo_cuenta,
               c.Saldo AS saldo, c.SaldoRetenido AS saldo_retenido,
               c.Estado AS estado
        FROM Cuentas.Cuenta AS c
        INNER JOIN ProductosFinancieros.Producto AS p
          ON p.IdProducto = c.IdProducto
        WHERE c.IdCuenta = :id_cuenta
        """,
        {"id_cuenta": id_cuenta},
    )
    return _cuenta_desde_bd(fila) if fila is not None else None


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
        SELECT TOP 1 ResultadoEvaluacion AS estado
        FROM Clientes.RiesgoCliente
        WHERE IdCliente = :id_cliente
          AND EsVigente = 1
        ORDER BY FechaEvaluacion DESC
        """,
        {"id_cliente": id_cliente},
    )


def obtener_subproducto(conn: Connection, id_subproducto: int) -> dict[str, Any] | None:
    """Devuelve el subproducto y su producto padre para validar CTA-01."""
    return _one(
        conn,
        """
        SELECT s.IdSubProducto AS id_subproducto,
               s.IdProducto AS id_producto,
               s.Estado AS estado_subproducto,
               p.TipoProducto AS tipo_producto,
               p.TipoCuenta AS tipo_cuenta,
               p.Estado AS estado_producto,
               p.MontoAperturaMinimo AS monto_apertura_minimo
        FROM ProductosFinancieros.SubProducto AS s
        INNER JOIN ProductosFinancieros.Producto AS p
          ON p.IdProducto = s.IdProducto
        WHERE s.IdSubProducto = :id_subproducto
        """,
        {"id_subproducto": id_subproducto},
    )


def obtener_agencia(conn: Connection, id_agencia: str) -> dict[str, Any] | None:
    """Devuelve {estado} de la agencia o None si no existe."""
    return _one(
        conn,
        """
        SELECT Estado AS estado
        FROM Organizacion.Agencia
        WHERE IdAgencia = :id_agencia
        """,
        {"id_agencia": id_agencia},
    )


# Apertura de la cuenta


def abrir_cuenta(
    conn: Connection,
    numero_cuenta: str,
    id_cliente: int,
    id_subproducto: int,
    id_agencia: str,
    monto_inicial: Decimal,
    creado_por: int,
) -> dict[str, Any]:
    """Ejecuta la firma real del SP y lee la cuenta por su id de salida."""
    salida = _one(
        conn,
        """
        DECLARE @id_cuenta int;
        EXEC Cuentas.usp_AbrirCuenta
            @IdCliente       = :id_cliente,
            @IdSubProducto   = :id_subproducto,
            @IdAgencia       = :id_agencia,
            @NumeroCuenta    = :numero_cuenta,
            @MontoInicial    = :monto_inicial,
            @CreadoPor       = :creado_por,
            @IdCuenta        = @id_cuenta OUTPUT;
        SELECT @id_cuenta AS id_cuenta;
        """,
        {
            "id_cliente": id_cliente,
            "id_subproducto": id_subproducto,
            "id_agencia": id_agencia,
            "numero_cuenta": numero_cuenta,
            "monto_inicial": monto_inicial,
            "creado_por": creado_por,
        },
    )
    cuenta = (
        obtener_cuenta_por_id(conn, int(salida["id_cuenta"]))
        if salida is not None and salida["id_cuenta"] is not None
        else None
    )
    if cuenta is None:  # pragma: no cover
        raise RuntimeError("usp_AbrirCuenta no devolvió la cuenta creada")

    return cuenta
