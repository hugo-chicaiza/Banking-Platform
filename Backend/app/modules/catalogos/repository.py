from typing import Any

from sqlalchemy import Connection, text


def _rows(
    conn: Connection, sql: str, parameters: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    return [
        dict(row) for row in conn.execute(text(sql), parameters or {}).mappings()
    ]


def listar_paises(conn: Connection) -> list[dict[str, Any]]:
    # CAT-01: la tabla no tiene Estado
    return _rows(
        conn,
        """
        SELECT CodigoPais AS codigo_pais, CodigoNumerico AS codigo_numerico,
               NombrePais AS nombre_pais
        FROM Catalogo.Paises
        ORDER BY NombrePais
        """,
    )


def listar_denominaciones(conn: Connection) -> list[dict[str, Any]]:
    # CAT-05: solo activas; billetes primero, luego valor descendente (orden de conteo)
    return _rows(
        conn,
        """
        SELECT IdDenominacion AS id_denominacion, TipoPieza AS tipo_pieza,
               Valor AS valor, Descripcion AS descripcion
        FROM Catalogo.Denominacion
        WHERE Estado = 'A'
        ORDER BY CASE TipoPieza WHEN 'Billete' THEN 0 ELSE 1 END, Valor DESC
        """,
    )


def listar_tipos_movimiento_caja(conn: Connection) -> list[dict[str, Any]]:
    # CAT-10: la tabla no tiene Estado
    return _rows(
        conn,
        """
        SELECT IdTipoMovimientoCaja AS id_tipo_movimiento_caja, Codigo AS codigo,
               Descripcion AS descripcion, Naturaleza AS naturaleza
        FROM Caja.TipoMovimientoCaja
        ORDER BY Naturaleza, Codigo
        """,
    )


def listar_agencias(conn: Connection) -> list[dict[str, Any]]:
    # CAT-06: la tabla Agencia no tiene Nombre; se usa Codigo como nombre (acordado
    # con el equipo). Provincia y ciudad vienen de Catalogo.Ciudad.
    return _rows(
        conn,
        """
        SELECT a.IdAgencia AS id_agencia, a.Codigo AS codigo,
               a.Codigo AS nombre, a.TipoAgencia AS tipo_agencia,
               c.Provincia AS provincia, c.Nombre AS ciudad,
               a.Estado AS estado
        FROM Organizacion.Agencia AS a
        JOIN Catalogo.Ciudad AS c ON c.IdCiudad = a.IdCiudad
        ORDER BY a.Codigo
        """,
    )


def listar_productos(conn: Connection, tipo: str | None = None) -> list[dict[str, Any]]:
    filtro_tipo = "\n          AND p.TipoProducto = :tipo" if tipo is not None else ""
    parametros = {"tipo": tipo} if tipo is not None else None
    return _rows(
        conn,
        f"""
        SELECT p.IdProducto AS id_producto,
               p.CodigoProducto AS codigo_producto,
               p.NombreProducto AS nombre_producto,
               p.TipoProducto AS tipo_producto,
               CASE WHEN p.TipoProducto = 'Cuenta'
                    THEN p.MontoAperturaMinimo END AS monto_apertura_minimo,
               CASE WHEN p.TipoProducto = 'Credito'
                    THEN p.IdTipoCredito END AS id_tipo_credito,
               CASE WHEN p.TipoProducto = 'Tarjeta'
                    THEN r.IdRed END AS id_red,
               CASE WHEN p.TipoProducto = 'Cuenta'
                    THEN p.TipoCuenta END AS tipo_cuenta,
               p.PermiteOperacionesPresenciales
                    AS permite_operaciones_presenciales
        FROM ProductosFinancieros.Producto AS p
        LEFT JOIN ProductosFinancieros.Red AS r ON r.IdRed = p.IdRed
        WHERE p.Estado = 'A'{filtro_tipo}
        ORDER BY p.TipoProducto, p.NombreProducto
        """,
        parametros,
    )
