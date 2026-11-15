from typing import Any

from sqlalchemy import Connection, text

_BLOQUEO = " WITH (UPDLOCK, ROWLOCK)"

_PRODUCTO = """
    SELECT p.IdProducto AS id_producto, p.CodigoProducto AS codigo_producto,
           p.NombreProducto AS nombre_producto, p.Descripcion AS descripcion,
           p.TipoProducto AS tipo_producto, p.TipoCuenta AS tipo_cuenta,
           CASE WHEN p.TipoProducto = 'Cuenta' THEN p.MontoAperturaMinimo END
               AS monto_apertura_minimo,
           p.IdTipoCredito AS id_tipo_credito, tc.Nombre AS nombre_tipo_credito,
           p.IdRed AS id_red, r.Nombre AS nombre_red,
           p.PermiteOperacionesPresenciales AS permite_operaciones_presenciales,
           p.Estado AS estado
    FROM ProductosFinancieros.Producto AS p{bloqueo}
    LEFT JOIN Credito.TipoCredito AS tc ON tc.IdTipoCredito = p.IdTipoCredito
    LEFT JOIN ProductosFinancieros.Red AS r ON r.IdRed = p.IdRed
"""

_SUBPRODUCTO = """
    SELECT IdSubProducto AS id_sub_producto, IdProducto AS id_producto,
           CodigoSubProducto AS codigo_sub_producto,
           NombreSubProducto AS nombre_sub_producto, Estado AS estado,
           FechaRegistro AS fecha_registro
    FROM ProductosFinancieros.SubProducto{bloqueo}
"""


def _rows(
    conn: Connection, sql: str, params: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(text(sql), params or {}).mappings()]


def listar_productos(conn: Connection) -> list[dict[str, Any]]:
    return _rows(
        conn,
        _PRODUCTO.format(bloqueo="") + " ORDER BY p.TipoProducto, p.NombreProducto",
    )


def listar_subproductos(
    conn: Connection, id_producto: int | None = None
) -> list[dict[str, Any]]:
    return _rows(
        conn,
        _SUBPRODUCTO.format(bloqueo="")
        + " WHERE (:id IS NULL OR IdProducto = :id) ORDER BY NombreSubProducto",
        {"id": id_producto},
    )


def obtener_producto(
    conn: Connection, id_producto: int, *, bloquear: bool = False
) -> dict[str, Any] | None:
    # UPDLOCK: un PATCH concurrente sobre el mismo producto espera al primero
    filas = _rows(
        conn,
        _PRODUCTO.format(bloqueo=_BLOQUEO if bloquear else "")
        + " WHERE p.IdProducto = :id",
        {"id": id_producto},
    )
    return filas[0] if filas else None


def obtener_subproducto(
    conn: Connection, id_sub: int, *, bloquear: bool = False
) -> dict[str, Any] | None:
    filas = _rows(
        conn,
        _SUBPRODUCTO.format(bloqueo=_BLOQUEO if bloquear else "")
        + " WHERE IdSubProducto = :id",
        {"id": id_sub},
    )
    return filas[0] if filas else None


def existe_tipo_credito_activo(conn: Connection, id_tipo_credito: int) -> bool:
    return bool(
        _rows(
            conn,
            "SELECT 1 AS x FROM Credito.TipoCredito WHERE IdTipoCredito = :id AND Estado = 'A'",
            {"id": id_tipo_credito},
        )
    )


def existe_red_activa(conn: Connection, id_red: int) -> bool:
    return bool(
        _rows(
            conn,
            "SELECT 1 AS x FROM ProductosFinancieros.Red WHERE IdRed = :id AND Estado = 'A'",
            {"id": id_red},
        )
    )


def insertar_producto(conn: Connection, datos: dict[str, Any]) -> int:
    return int(
        conn.execute(
            text(
                """
                INSERT INTO ProductosFinancieros.Producto (
                    CodigoProducto, NombreProducto, Descripcion, TipoProducto,
                    MontoAperturaMinimo, IdTipoCredito, IdRed, TipoCuenta,
                    PermiteOperacionesPresenciales, Estado)
                OUTPUT inserted.IdProducto
                VALUES (:codigo_producto, :nombre_producto, :descripcion, :tipo_producto,
                        :monto_apertura_minimo, :id_tipo_credito, :id_red, :tipo_cuenta,
                        :permite_operaciones_presenciales, 'I')
                """
            ),
            datos,
        ).scalar_one()
    )


_COLUMNAS_PRODUCTO = {
    "nombre_producto": "NombreProducto",
    "descripcion": "Descripcion",
    "monto_apertura_minimo": "MontoAperturaMinimo",
    "permite_operaciones_presenciales": "PermiteOperacionesPresenciales",
    "estado": "Estado",
}
_COLUMNAS_SUBPRODUCTO = {"nombre_sub_producto": "NombreSubProducto", "estado": "Estado"}


def _actualizar(
    conn: Connection,
    tabla: str,
    columnas: dict[str, str],
    clave: str,
    id_: int,
    cambios: dict[str, Any],
) -> None:
    # Las columnas salen de una lista blanca fija, nunca del cliente
    sets = ", ".join(f"{columnas[c]} = :{c}" for c in cambios)
    conn.execute(
        text(f"UPDATE {tabla} SET {sets} WHERE {clave} = :id"), {**cambios, "id": id_}
    )


def actualizar_producto(
    conn: Connection, id_producto: int, cambios: dict[str, Any]
) -> None:
    _actualizar(
        conn,
        "ProductosFinancieros.Producto",
        _COLUMNAS_PRODUCTO,
        "IdProducto",
        id_producto,
        cambios,
    )


def insertar_subproducto(
    conn: Connection, id_producto: int, codigo: str, nombre: str
) -> int:
    return int(
        conn.execute(
            text(
                """
                INSERT INTO ProductosFinancieros.SubProducto (IdProducto, CodigoSubProducto, NombreSubProducto, Estado)
                OUTPUT inserted.IdSubProducto
                VALUES (:id_producto, :codigo, :nombre, 'A')
                """
            ),
            {"id_producto": id_producto, "codigo": codigo, "nombre": nombre},
        ).scalar_one()
    )


def actualizar_subproducto(
    conn: Connection, id_sub: int, cambios: dict[str, Any]
) -> None:
    _actualizar(
        conn,
        "ProductosFinancieros.SubProducto",
        _COLUMNAS_SUBPRODUCTO,
        "IdSubProducto",
        id_sub,
        cambios,
    )
