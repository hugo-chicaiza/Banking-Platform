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


_CAMPOS_PRODUCTO = (
    "nombre_producto",
    "descripcion",
    "monto_apertura_minimo",
    "permite_operaciones_presenciales",
    "estado",
)
_CAMPOS_SUBPRODUCTO = ("nombre_sub_producto", "estado")


def _parametros(
    campos: tuple[str, ...], id_: int, cambios: dict[str, Any]
) -> dict[str, Any]:
    """Cada campo lleva su bandera "cambia_*": el SQL es fijo y solo se escriben los presentes.

    Así descripcion=None (borrarla) se distingue de "no se envió".
    """
    desconocidos = set(cambios) - set(campos)
    if desconocidos:
        raise ValueError(f"Campos no editables: {sorted(desconocidos)}")
    parametros: dict[str, Any] = {"id": id_}
    for campo in campos:
        parametros[f"cambia_{campo}"] = campo in cambios
        parametros[campo] = cambios.get(campo)
    return parametros


def actualizar_producto(
    conn: Connection, id_producto: int, cambios: dict[str, Any]
) -> None:
    conn.execute(
        text(
            """
            UPDATE ProductosFinancieros.Producto SET
                NombreProducto = CASE WHEN :cambia_nombre_producto = 1
                    THEN :nombre_producto ELSE NombreProducto END,
                Descripcion = CASE WHEN :cambia_descripcion = 1
                    THEN :descripcion ELSE Descripcion END,
                MontoAperturaMinimo = CASE WHEN :cambia_monto_apertura_minimo = 1
                    THEN :monto_apertura_minimo ELSE MontoAperturaMinimo END,
                PermiteOperacionesPresenciales =
                    CASE WHEN :cambia_permite_operaciones_presenciales = 1
                    THEN :permite_operaciones_presenciales
                    ELSE PermiteOperacionesPresenciales END,
                Estado = CASE WHEN :cambia_estado = 1 THEN :estado ELSE Estado END
            WHERE IdProducto = :id
            """
        ),
        _parametros(_CAMPOS_PRODUCTO, id_producto, cambios),
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
    conn.execute(
        text(
            """
            UPDATE ProductosFinancieros.SubProducto SET
                NombreSubProducto = CASE WHEN :cambia_nombre_sub_producto = 1
                    THEN :nombre_sub_producto ELSE NombreSubProducto END,
                Estado = CASE WHEN :cambia_estado = 1 THEN :estado ELSE Estado END
            WHERE IdSubProducto = :id
            """
        ),
        _parametros(_CAMPOS_SUBPRODUCTO, id_sub, cambios),
    )
