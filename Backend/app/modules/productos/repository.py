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
           FechaRegistro AS fecha_registro, EdadMinima AS edad_minima,
           EdadMaxima AS edad_maxima
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
    "codigo_producto",
    "nombre_producto",
    "descripcion",
    "monto_apertura_minimo",
    "permite_operaciones_presenciales",
    "estado",
)
_CAMPOS_SUBPRODUCTO = ("nombre_sub_producto", "estado", "edad_minima", "edad_maxima")


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
                CodigoProducto = CASE WHEN :cambia_codigo_producto = 1
                    THEN :codigo_producto ELSE CodigoProducto END,
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
    conn: Connection,
    id_producto: int,
    codigo: str,
    nombre: str,
    edad_minima: int | None = None,
    edad_maxima: int | None = None,
) -> int:
    return int(
        conn.execute(
            text(
                """
                INSERT INTO ProductosFinancieros.SubProducto (IdProducto, CodigoSubProducto,
                    NombreSubProducto, Estado, EdadMinima, EdadMaxima)
                OUTPUT inserted.IdSubProducto
                VALUES (:id_producto, :codigo, :nombre, 'A', :edad_minima, :edad_maxima)
                """
            ),
            {
                "id_producto": id_producto,
                "codigo": codigo,
                "nombre": nombre,
                "edad_minima": edad_minima,
                "edad_maxima": edad_maxima,
            },
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
                Estado = CASE WHEN :cambia_estado = 1 THEN :estado ELSE Estado END,
                EdadMinima = CASE WHEN :cambia_edad_minima = 1
                    THEN :edad_minima ELSE EdadMinima END,
                EdadMaxima = CASE WHEN :cambia_edad_maxima = 1
                    THEN :edad_maxima ELSE EdadMaxima END
            WHERE IdSubProducto = :id
            """
        ),
        _parametros(_CAMPOS_SUBPRODUCTO, id_sub, cambios),
    )


# ---------- Cupos por canal ----------


def listar_cupos(conn: Connection, id_sub: int) -> list[dict[str, Any]]:
    """Cada canal activo (o ya habilitado), con los máximos del subproducto."""
    return _rows(
        conn,
        """
        SELECT c.IdCanal AS id_canal, c.CodigoCanal AS codigo_canal,
               c.NombreCanal AS nombre_canal,
               CAST(CASE WHEN p.IdProductoCanalCupo IS NULL THEN 0 ELSE 1 END AS bit)
                   AS habilitado,
               p.CupoDiarioMaximo AS cupo_diario_maximo,
               p.CupoMensualMaximo AS cupo_mensual_maximo,
               p.MontoMaxTransaccion AS monto_max_transaccion,
               p.MaxTransaccionesDia AS max_transacciones_dia
        FROM Canal.Canal AS c
        LEFT JOIN ProductosFinancieros.ProductoCanalCupo AS p
          ON p.IdCanal = c.IdCanal AND p.IdSubProducto = :id
        WHERE c.Estado = 'A' OR p.IdProductoCanalCupo IS NOT NULL
        ORDER BY c.NombreCanal
        """,
        {"id": id_sub},
    )


def canales_activos(conn: Connection) -> set[int]:
    return {
        int(i)
        for i in conn.execute(
            text("SELECT IdCanal FROM Canal.Canal WHERE Estado = 'A'")
        ).scalars()
    }


def cupos_personalizados_maximos(
    conn: Connection, id_sub: int
) -> dict[int, dict[str, Any]]:
    """Por canal, lo más alto que ya personalizaron las cuentas del subproducto (CTA-08)."""
    return {
        int(f["id_canal"]): f
        for f in _rows(
            conn,
            """
            SELECT cc.IdCanal AS id_canal, MAX(cc.CupoDiario) AS cupo_diario,
                   MAX(cc.CupoMensual) AS cupo_mensual,
                   MAX(cc.MontoMaxTransaccion) AS monto_max_transaccion
            FROM Canal.CanalCupoClienteCustom AS cc WITH (HOLDLOCK)
            JOIN Cuentas.Cuenta AS cu ON cu.IdCuenta = cc.IdCuenta
            WHERE cu.IdSubProducto = :id AND cc.Estado = 'A'
            GROUP BY cc.IdCanal
            """,
            {"id": id_sub},
        )
    }


def guardar_cupos(conn: Connection, id_sub: int, cupos: list[dict[str, Any]]) -> None:
    """Quita los canales que no vienen y crea o actualiza los que sí (en la transacción)."""
    actuales = {
        int(i)
        for i in conn.execute(
            text(
                "SELECT IdCanal FROM ProductosFinancieros.ProductoCanalCupo"
                " WITH (UPDLOCK, HOLDLOCK) WHERE IdSubProducto = :id"
            ),
            {"id": id_sub},
        ).scalars()
    }
    for id_canal in actuales - {c["id_canal"] for c in cupos}:
        conn.execute(
            text(
                "DELETE FROM ProductosFinancieros.ProductoCanalCupo"
                " WHERE IdSubProducto = :id AND IdCanal = :canal"
            ),
            {"id": id_sub, "canal": id_canal},
        )
    for cupo in cupos:
        conn.execute(
            text(
                """
                MERGE ProductosFinancieros.ProductoCanalCupo WITH (HOLDLOCK) AS d
                USING (SELECT :id AS IdSubProducto, :id_canal AS IdCanal) AS o
                   ON d.IdSubProducto = o.IdSubProducto AND d.IdCanal = o.IdCanal
                WHEN MATCHED THEN UPDATE SET
                    CupoDiarioMaximo = :cupo_diario_maximo,
                    CupoMensualMaximo = :cupo_mensual_maximo,
                    MontoMaxTransaccion = :monto_max_transaccion,
                    MaxTransaccionesDia = :max_transacciones_dia
                WHEN NOT MATCHED THEN INSERT (IdSubProducto, IdCanal, CupoDiarioMaximo,
                    CupoMensualMaximo, MontoMaxTransaccion, MaxTransaccionesDia)
                    VALUES (:id, :id_canal, :cupo_diario_maximo, :cupo_mensual_maximo,
                            :monto_max_transaccion, :max_transacciones_dia);
                """
            ),
            {"id": id_sub, **cupo},
        )


# ---------- Restricciones de cuenta ----------


def obtener_restricciones(conn: Connection, id_sub: int) -> dict[str, Any]:
    filas = _rows(
        conn,
        """
        SELECT TipoRestriccion AS tipo, Dias AS dias, Monto AS monto
        FROM ProductosFinancieros.ProductoRestriccion
        WHERE IdSubProducto = :id AND Estado = 'A'
        """,
        {"id": id_sub},
    )
    por_tipo = {f["tipo"]: f for f in filas}
    return {
        "dias_sin_retiros": por_tipo.get("SIN_RETIROS", {}).get("dias"),
        "saldo_minimo": por_tipo.get("SALDO_MINIMO", {}).get("monto"),
    }


def guardar_restriccion(
    conn: Connection,
    id_sub: int,
    tipo: str,
    dias: int | None,
    monto: Any,
    descripcion: str,
    id_usuario: int,
) -> None:
    """Una fila por tipo (UX_ProductoRestriccion_Activa): se actualiza, se activa o se
    inactiva; nunca se borra. Sin valor = inactiva."""
    activa = dias is not None or monto is not None
    parametros = {
        "id": id_sub,
        "tipo": tipo,
        "activa": activa,
        "dias": dias,
        "monto": monto,
        "descripcion": descripcion,
        "usuario": id_usuario,
    }
    actualizadas = conn.execute(
        text(
            """
            UPDATE ProductosFinancieros.ProductoRestriccion WITH (UPDLOCK, HOLDLOCK)
            SET Dias = CASE WHEN :activa = 1 THEN :dias ELSE Dias END,
                Monto = CASE WHEN :activa = 1 THEN :monto ELSE Monto END,
                Descripcion = CASE WHEN :activa = 1 THEN :descripcion ELSE Descripcion END,
                Estado = CASE WHEN :activa = 1 THEN 'A' ELSE 'I' END,
                RegistradoPor = :usuario
            WHERE IdSubProducto = :id AND TipoRestriccion = :tipo
            """
        ),
        parametros,
    ).rowcount
    if actualizadas == 0 and activa:
        conn.execute(
            text(
                """
                INSERT INTO ProductosFinancieros.ProductoRestriccion (IdSubProducto,
                    TipoRestriccion, Dias, Monto, Descripcion, VigenciaDesde, Estado,
                    RegistradoPor)
                VALUES (:id, :tipo, :dias, :monto, :descripcion,
                        CAST(SYSUTCDATETIME() AS date), 'A', :usuario)
                """
            ),
            parametros,
        )


# ---------- Uso y eliminación de un producto en borrador ----------


def producto_en_uso(conn: Connection, id_producto: int) -> bool:
    """Cuentas, tarjetas o solicitudes de crédito que lo usan (nunca se elimina entonces)."""
    return bool(
        conn.execute(
            text(
                """
                SELECT CASE WHEN EXISTS (SELECT 1 FROM Cuentas.Cuenta WHERE IdProducto = :id)
                    OR EXISTS (SELECT 1 FROM Tarjeta.Tarjeta WHERE IdProducto = :id)
                    OR EXISTS (SELECT 1 FROM Credito.CreditoSolicitud WHERE IdProducto = :id)
                THEN 1 ELSE 0 END
                """
            ),
            {"id": id_producto},
        ).scalar_one()
    )


def eliminar_producto(conn: Connection, id_producto: int) -> None:
    """Borra el producto, sus subproductos y lo que cuelga de ellos (en la transacción).
    Solo para un producto inactivo y sin uso: lo valida el servicio."""
    for sql in (
        """
        DELETE FROM ProductosFinancieros.ProductoTasaInteres
        WHERE IdProducto = :id OR IdSubProducto IN (SELECT IdSubProducto FROM ProductosFinancieros.SubProducto WHERE IdProducto = :id)
        """,
        """
        DELETE FROM ProductosFinancieros.ProductoComision
        WHERE IdProducto = :id OR IdSubProducto IN (SELECT IdSubProducto FROM ProductosFinancieros.SubProducto WHERE IdProducto = :id)
        """,
        """
        DELETE FROM ProductosFinancieros.ProductoSeguro
        WHERE IdProducto = :id OR IdSubProducto IN (SELECT IdSubProducto FROM ProductosFinancieros.SubProducto WHERE IdProducto = :id)
        """,
        """
        DELETE FROM ProductosFinancieros.ProductoSistemaAmortizacion
        WHERE IdProducto = :id OR IdSubProducto IN (SELECT IdSubProducto FROM ProductosFinancieros.SubProducto WHERE IdProducto = :id)
        """,
        """
        DELETE FROM ProductosFinancieros.ProductoCanalCupo
        WHERE IdSubProducto IN (SELECT IdSubProducto FROM ProductosFinancieros.SubProducto WHERE IdProducto = :id)
        """,
        """
        DELETE FROM ProductosFinancieros.ProductoRestriccion
        WHERE IdSubProducto IN (SELECT IdSubProducto FROM ProductosFinancieros.SubProducto WHERE IdProducto = :id)
        """,
        "DELETE FROM ProductosFinancieros.SubProducto WHERE IdProducto = :id",
        "DELETE FROM ProductosFinancieros.Producto WHERE IdProducto = :id",
    ):
        conn.execute(text(sql), {"id": id_producto})
