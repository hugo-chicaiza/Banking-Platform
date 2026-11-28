from datetime import date
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
           p.Estado AS estado, p.EstadoProducto AS estado_catalogo,
           p.IdTipoProducto AS id_tipo_producto
    FROM ProductosFinancieros.Producto AS p{bloqueo}
    LEFT JOIN Credito.TipoCredito AS tc ON tc.IdTipoCredito = p.IdTipoCredito
    LEFT JOIN ProductosFinancieros.Red AS r ON r.IdRed = p.IdRed
"""

_SUBPRODUCTO = """
    SELECT IdSubProducto AS id_sub_producto, IdProducto AS id_producto,
           CodigoSubProducto AS codigo_sub_producto,
           NombreSubProducto AS nombre_sub_producto, Estado AS estado,
           FechaRegistro AS fecha_registro, EdadMinima AS edad_minima,
           EdadMaxima AS edad_maxima, EstadoSubProducto AS estado_catalogo,
           TipoClientePermitido AS tipo_cliente_permitido, RequiereTutor AS requiere_tutor,
           IdSubProductoRequerido AS id_sub_producto_requerido,
           MaximoPorCliente AS maximo_por_cliente
    FROM ProductosFinancieros.SubProducto{bloqueo}
"""


def _rows(
    conn: Connection, sql: str, params: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(text(sql), params or {}).mappings()]


def listar_tipos(conn: Connection) -> list[dict[str, Any]]:
    return _rows(
        conn,
        """
        SELECT IdTipoProducto AS id_tipo_producto, Codigo AS codigo, Nombre AS nombre,
            CASE Codigo WHEN 'CREDITO' THEN 'Credito' WHEN 'TARJETA' THEN 'Tarjeta'
                 ELSE 'Cuenta' END AS tipo_producto,
            CASE Codigo WHEN 'CUENTA_CORRIENTE' THEN 'Corriente'
                 WHEN 'CUENTA_AHORRO' THEN 'Ahorro'
                 WHEN 'CERTIFICADO_APORTACION' THEN 'CERTIFICADO_APORTACION' END AS tipo_cuenta
        FROM ProductosFinancieros.TipoProducto WHERE Estado = 'A' ORDER BY IdTipoProducto
    """,
    )


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
                    PermiteOperacionesPresenciales, Estado, EstadoProducto, IdTipoProducto)
                OUTPUT inserted.IdProducto
                VALUES (:codigo_producto, :nombre_producto, :descripcion, :tipo_producto,
                        :monto_apertura_minimo, :id_tipo_credito, :id_red, :tipo_cuenta,
                        :permite_operaciones_presenciales, 'I', 'Borrador', :id_tipo_producto)
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
    "estado_catalogo",
)
_CAMPOS_SUBPRODUCTO = (
    "nombre_sub_producto",
    "estado",
    "estado_catalogo",
    "edad_minima",
    "edad_maxima",
    "tipo_cliente_permitido",
    "requiere_tutor",
    "id_sub_producto_requerido",
    "maximo_por_cliente",
)


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
                Estado = CASE WHEN :cambia_estado = 1 THEN :estado ELSE Estado END,
                EstadoProducto = CASE WHEN :cambia_estado_catalogo = 1 THEN :estado_catalogo ELSE EstadoProducto END
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
    *,
    tipo_cliente_permitido: str = "Ambos",
    requiere_tutor: bool = False,
    id_sub_producto_requerido: int | None = None,
    maximo_por_cliente: int | None = None,
) -> int:
    return int(
        conn.execute(
            text(
                """
                INSERT INTO ProductosFinancieros.SubProducto (IdProducto, CodigoSubProducto,
                    NombreSubProducto, Estado, EdadMinima, EdadMaxima, EstadoSubProducto,
                    TipoClientePermitido, RequiereTutor, IdSubProductoRequerido, MaximoPorCliente)
                OUTPUT inserted.IdSubProducto
                VALUES (:id_producto, :codigo, :nombre, 'I', :edad_minima, :edad_maxima, 'Borrador',
                        :tipo_cliente_permitido, :requiere_tutor, :id_sub_producto_requerido, :maximo_por_cliente)
                """
            ),
            {
                "id_producto": id_producto,
                "codigo": codigo,
                "nombre": nombre,
                "edad_minima": edad_minima,
                "edad_maxima": edad_maxima,
                "tipo_cliente_permitido": tipo_cliente_permitido,
                "requiere_tutor": requiere_tutor,
                "id_sub_producto_requerido": id_sub_producto_requerido,
                "maximo_por_cliente": maximo_por_cliente,
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
                EstadoSubProducto = CASE WHEN :cambia_estado_catalogo = 1 THEN :estado_catalogo ELSE EstadoSubProducto END,
                EdadMinima = CASE WHEN :cambia_edad_minima = 1
                    THEN :edad_minima ELSE EdadMinima END,
                EdadMaxima = CASE WHEN :cambia_edad_maxima = 1
                    THEN :edad_maxima ELSE EdadMaxima END,
                TipoClientePermitido = CASE WHEN :cambia_tipo_cliente_permitido = 1 THEN :tipo_cliente_permitido ELSE TipoClientePermitido END,
                RequiereTutor = CASE WHEN :cambia_requiere_tutor = 1 THEN :requiere_tutor ELSE RequiereTutor END,
                IdSubProductoRequerido = CASE WHEN :cambia_id_sub_producto_requerido = 1 THEN :id_sub_producto_requerido ELSE IdSubProductoRequerido END,
                MaximoPorCliente = CASE WHEN :cambia_maximo_por_cliente = 1 THEN :maximo_por_cliente ELSE MaximoPorCliente END
            WHERE IdSubProducto = :id
            """
        ),
        _parametros(_CAMPOS_SUBPRODUCTO, id_sub, cambios),
    )


# ---------- Cupos por canal ----------


def listar_cupos(conn: Connection, id_sub: int) -> list[dict[str, Any]]:
    """Vista de cupos activos a la fecha de la BD, sin duplicar canales históricos."""
    return _rows(
        conn,
        """
        SELECT c.IdCanal AS id_canal, c.CodigoCanal AS codigo_canal,
               c.NombreCanal AS nombre_canal,
               CAST(CASE WHEN p.IdProductoCanalCupo IS NULL THEN 0 ELSE 1 END AS bit) AS habilitado,
               p.CupoDiarioMaximo AS cupo_diario_maximo,
               p.CupoMensualMaximo AS cupo_mensual_maximo,
               p.MontoMaxTransaccion AS monto_max_transaccion,
               p.MaxTransaccionesDia AS max_transacciones_dia
        FROM Canal.Canal AS c
        OUTER APPLY (
            SELECT TOP (1) x.* FROM ProductosFinancieros.ProductoCanalCupo AS x
            WHERE x.IdCanal = c.IdCanal AND x.IdSubProducto = :id
              AND x.EstadoCupo = 'A'
              AND x.VigenciaDesde <= CONVERT(date, SYSDATETIMEOFFSET() AT TIME ZONE 'SA Pacific Standard Time')
              AND (x.VigenciaHasta IS NULL OR x.VigenciaHasta >= CONVERT(date, SYSDATETIMEOFFSET() AT TIME ZONE 'SA Pacific Standard Time'))
            ORDER BY x.VigenciaDesde DESC, x.IdProductoCanalCupo DESC
        ) AS p
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
    """Versiona cupos sin DELETE. Debe llamarse dentro de una transacción."""
    hoy = conn.execute(
        text(
            "SELECT CONVERT(date, SYSDATETIMEOFFSET() AT TIME ZONE 'SA Pacific Standard Time')"
        )
    ).scalar_one()
    actuales = _rows(
        conn,
        """
        SELECT IdProductoCanalCupo AS id, IdCanal AS canal, VigenciaDesde AS desde
        FROM ProductosFinancieros.ProductoCanalCupo WITH (UPDLOCK, HOLDLOCK)
        WHERE IdSubProducto = :id AND EstadoCupo = 'A'
          AND VigenciaDesde <= :hoy AND (VigenciaHasta IS NULL OR VigenciaHasta >= :hoy)
    """,
        {"id": id_sub, "hoy": hoy},
    )
    if len({f["canal"] for f in actuales}) != len(actuales):
        raise ValueError("Existen cupos vigentes superpuestos; no se puede versionar")
    futuros = _rows(
        conn,
        """
        SELECT IdProductoCanalCupo FROM ProductosFinancieros.ProductoCanalCupo WITH (UPDLOCK, HOLDLOCK)
        WHERE IdSubProducto = :id AND EstadoCupo = 'A' AND VigenciaDesde > :hoy
    """,
        {"id": id_sub, "hoy": hoy},
    )
    if futuros:
        raise ValueError("Existen cupos futuros programados; revisar antes de guardar")
    por_canal = {int(f["canal"]): f for f in actuales}
    nuevos = {int(c["id_canal"]): c for c in cupos}
    for canal, anterior in por_canal.items():
        if anterior["desde"] == hoy:
            if canal not in nuevos:
                conn.execute(
                    text("""
                    UPDATE ProductosFinancieros.ProductoCanalCupo SET EstadoCupo = 'I'
                    WHERE IdProductoCanalCupo = :id
                """),
                    {"id": anterior["id"]},
                )
            else:
                c = nuevos[canal]
                conn.execute(
                    text("""
                    UPDATE ProductosFinancieros.ProductoCanalCupo SET
                        CupoDiarioMaximo = :cupo_diario_maximo,
                        CupoMensualMaximo = :cupo_mensual_maximo,
                        MontoMaxTransaccion = :monto_max_transaccion,
                        MaxTransaccionesDia = :max_transacciones_dia
                    WHERE IdProductoCanalCupo = :id
                """),
                    {**c, "id": anterior["id"]},
                )
        else:
            conn.execute(
                text("""
                UPDATE ProductosFinancieros.ProductoCanalCupo
                SET VigenciaHasta = DATEADD(day, -1, :hoy)
                WHERE IdProductoCanalCupo = :id
            """),
                {"id": anterior["id"], "hoy": hoy},
            )
    for canal, c in nuevos.items():
        if canal in por_canal and por_canal[canal]["desde"] == hoy:
            continue
        conn.execute(
            text("""
            INSERT INTO ProductosFinancieros.ProductoCanalCupo
                (IdSubProducto, IdCanal, CupoDiarioMaximo, CupoMensualMaximo,
                 MontoMaxTransaccion, MaxTransaccionesDia, VigenciaDesde, EstadoCupo)
            VALUES (:id, :id_canal, :cupo_diario_maximo, :cupo_mensual_maximo,
                    :monto_max_transaccion, :max_transacciones_dia, :hoy, 'A')
        """),
            {"id": id_sub, "hoy": hoy, **c},
        )


# ---------- Restricciones de cuenta ----------


def obtener_restricciones(
    conn: Connection,
    id_sub: int,
) -> dict[str, Any]:
    """Consulta las restricciones activas y vigentes del subproducto.

    Considera la fecha actual de la base de datos y excluye
    restricciones futuras o vencidas.
    """
    filas = _rows(
        conn,
        """
        SELECT
            TipoRestriccion AS tipo,
            Dias AS dias,
            Monto AS monto
        FROM ProductosFinancieros.ProductoRestriccion
        WHERE IdSubProducto = :id
          AND Estado = 'A'
          AND VigenciaDesde <= CAST(
              SYSDATETIMEOFFSET() AT TIME ZONE
              'SA Pacific Standard Time' AS date
          )
          AND (
              VigenciaHasta IS NULL
              OR VigenciaHasta >= CAST(
                  SYSDATETIMEOFFSET() AT TIME ZONE
                  'SA Pacific Standard Time' AS date
              )
          )
        """,
        {"id": id_sub},
    )

    por_tipo = {fila["tipo"]: fila for fila in filas}

    return {
        "dias_sin_retiros": por_tipo.get(
            "SIN_RETIROS_DIAS", por_tipo.get("SIN_RETIROS", {})
        ).get("dias"),
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
        # La instalacion puede usar solo ProductoComision; no bloquear el
        # borrado si aun no existe este vinculo adicional de E3-01.
        """
        IF OBJECT_ID(N'ProductosFinancieros.SubProductoComision', N'U') IS NOT NULL
            EXEC sys.sp_executesql
                N'DELETE FROM ProductosFinancieros.SubProductoComision
                  WHERE IdSubProducto IN (SELECT IdSubProducto
                      FROM ProductosFinancieros.SubProducto WHERE IdProducto = @id)',
                N'@id int', @id = :id
        """,
        "DELETE FROM ProductosFinancieros.SubProductoCondicion WHERE IdSubProducto IN (SELECT IdSubProducto FROM ProductosFinancieros.SubProducto WHERE IdProducto = :id)",
        "DELETE FROM ProductosFinancieros.SubProducto WHERE IdProducto = :id",
        "DELETE FROM ProductosFinancieros.Producto WHERE IdProducto = :id",
    ):
        conn.execute(text(sql), {"id": id_producto})


# ---------- E3-01: servicios internos de vigencia ----------


def _fecha(fecha_contable: date) -> date:
    if not isinstance(fecha_contable, date):
        raise TypeError("fecha_contable debe ser date")
    return fecha_contable


def condiciones_vigentes(
    conn: Connection, id_subproducto: int, fecha_contable: date, canal: str
) -> dict[str, Any] | None:
    """Devuelve condiciones aplicables o None. El canal es obligatorio aunque
    las condiciones actuales sean globales; no se presume ventanilla.
    """
    if not canal or not canal.strip():
        raise ValueError("canal es obligatorio")
    fila = (
        conn.execute(
            text("""
            SELECT TOP (1) c.IdCondicion AS id_condicion,
                c.IdSubProducto AS id_subproducto,
                c.MontoAperturaMinimo AS monto_apertura_minimo,
                c.SaldoMinimo AS saldo_minimo,
                c.TasaInteresAnual AS tasa_interes_anual,
                c.PeriodicidadInteres AS periodicidad_interes,
                c.CostoMantenimiento AS costo_mantenimiento,
                c.PeriodicidadCosto AS periodicidad_costo,
                c.MesesInactividad AS meses_inactividad,
                c.AplicaACuentasExistentes AS aplica_a_cuentas_existentes,
                c.VigenciaDesde AS vigencia_desde,
                c.VigenciaHasta AS vigencia_hasta
            FROM ProductosFinancieros.SubProductoCondicion AS c
            WHERE c.IdSubProducto = :id
              AND c.Estado IN ('Vigente', 'Programada')
              AND c.VigenciaDesde <= :fecha
              AND (c.VigenciaHasta IS NULL OR c.VigenciaHasta >= :fecha)
            ORDER BY c.VigenciaDesde DESC, c.IdCondicion DESC
        """),
            {"id": id_subproducto, "fecha": _fecha(fecha_contable)},
        )
        .mappings()
        .first()
    )
    return dict(fila) if fila is not None else None


def cupo_vigente(
    conn: Connection, id_subproducto: int, fecha_contable: date, canal: str
) -> dict[str, Any]:
    """Sin canal activo o sin cupo vigente: permitido=False (denegar por defecto)."""
    if not canal or not canal.strip():
        raise ValueError("canal es obligatorio")
    fila = (
        conn.execute(
            text("""
            SELECT TOP (1) cc.IdProductoCanalCupo AS id_cupo,
                cc.CupoDiarioMaximo AS cupo_diario_maximo,
                cc.CupoMensualMaximo AS cupo_mensual_maximo,
                cc.MontoMaxTransaccion AS monto_max_transaccion,
                cc.MaxTransaccionesDia AS max_transacciones_dia,
                cc.VigenciaDesde AS vigencia_desde,
                cc.VigenciaHasta AS vigencia_hasta
            FROM ProductosFinancieros.ProductoCanalCupo AS cc
            JOIN Canal.Canal AS ca ON ca.IdCanal = cc.IdCanal
            WHERE cc.IdSubProducto = :id
              AND ca.CodigoCanal = :canal AND ca.Estado = 'A'
              AND cc.EstadoCupo = 'A'
              AND cc.VigenciaDesde <= :fecha
              AND (cc.VigenciaHasta IS NULL OR cc.VigenciaHasta >= :fecha)
            ORDER BY cc.VigenciaDesde DESC, cc.IdProductoCanalCupo DESC
        """),
            {
                "id": id_subproducto,
                "fecha": _fecha(fecha_contable),
                "canal": canal.strip(),
            },
        )
        .mappings()
        .first()
    )
    if fila is None:
        return {"permitido": False, "motivo": "CANAL_SIN_CUPO_VIGENTE"}
    return {"permitido": True, **dict(fila)}


def restricciones_vigentes(
    conn: Connection, id_subproducto: int, fecha_contable: date, canal: str
) -> list[dict[str, Any]]:
    """Lista restricciones aplicables; las restricciones actuales son globales al canal."""
    if not canal or not canal.strip():
        raise ValueError("canal es obligatorio")
    filas = (
        conn.execute(
            text("""
            SELECT IdRestriccion AS id_restriccion,
                TipoRestriccion AS tipo_restriccion,
                Dias AS dias, Monto AS monto, Cantidad AS cantidad,
                Descripcion AS descripcion,
                VigenciaDesde AS vigencia_desde,
                VigenciaHasta AS vigencia_hasta
            FROM ProductosFinancieros.ProductoRestriccion
            WHERE IdSubProducto = :id AND Estado = 'A'
              AND VigenciaDesde <= :fecha
              AND (VigenciaHasta IS NULL OR VigenciaHasta >= :fecha)
            ORDER BY TipoRestriccion, VigenciaDesde DESC
        """),
            {"id": id_subproducto, "fecha": _fecha(fecha_contable)},
        )
        .mappings()
        .all()
    )
    return [dict(fila) for fila in filas]


# ---------- E3-01: datos para elegibilidad ----------


def datos_elegibilidad(
    conn: Connection, id_cliente: int, id_subproducto: int
) -> dict[str, Any] | None:
    """Consulta los atributos sin exponer datos personales en la respuesta."""
    filas = _rows(
        conn,
        """
        SELECT c.TipoCliente AS tipo_cliente, c.FechaNacimiento AS fecha_nacimiento,
               c.Estado AS estado_cliente,
               s.IdSubProducto AS id_subproducto, s.CodigoSubProducto AS codigo_sub_producto,
               s.TipoClientePermitido AS tipo_permitido,
               s.EdadMinima AS edad_minima, s.EdadMaxima AS edad_maxima,
               s.RequiereTutor AS requiere_tutor,
               s.IdSubProductoRequerido AS id_requerido,
               s.MaximoPorCliente AS maximo_por_cliente,
               s.Estado AS estado_subproducto, s.EstadoSubProducto AS estado_subproducto_nuevo,
               p.Estado AS estado_producto, p.EstadoProducto AS estado_producto_nuevo,
               p.TipoProducto AS tipo_producto
        FROM Clientes.Cliente AS c
        CROSS JOIN ProductosFinancieros.SubProducto AS s
        JOIN ProductosFinancieros.Producto AS p ON p.IdProducto = s.IdProducto
        WHERE c.IdCliente = :cliente AND s.IdSubProducto = :sub
    """,
        {"cliente": id_cliente, "sub": id_subproducto},
    )
    return filas[0] if filas else None


def cuentas_cliente_para_elegibilidad(
    conn: Connection, id_cliente: int
) -> list[dict[str, Any]]:
    return _rows(
        conn,
        """
        SELECT IdSubProducto AS id_subproducto, Estado AS estado
        FROM Cuentas.Cuenta WHERE IdCliente = :cliente
    """,
        {"cliente": id_cliente},
    )


def tarjetas_cliente_para_elegibilidad(
    conn: Connection, id_cliente: int
) -> list[dict[str, Any]]:
    return _rows(
        conn,
        """
        SELECT IdSubProducto AS id_subproducto, Estado AS estado
        FROM Tarjeta.Tarjeta WHERE IdCliente = :cliente
    """,
        {"cliente": id_cliente},
    )
