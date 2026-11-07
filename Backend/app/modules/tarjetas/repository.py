from datetime import date
from typing import Any

from sqlalchemy import Connection, text

_COLUMNAS_TARJETA = """
    IdTarjeta AS id_tarjeta,
    TokenTarjeta AS token_tarjeta,
    RTRIM(NumeroEnmascarado) AS numero_enmascarado,
    TipoTarjeta AS tipo_tarjeta,
    NombreTarjeta AS nombre_tarjeta,
    IdCliente AS id_cliente,
    IdCuenta AS id_cuenta,
    IdProducto AS id_producto,
    Estado AS estado_actual,
    PinAsignado AS pin_asignado,
    FechaEmision AS fecha_emision,
    FechaExpiracion AS fecha_expiracion
"""

# Campos por los que se puede ordenar. El valor de sort nunca se concatena al SQL
CAMPOS_ORDEN_TARJETAS = {
    "idTarjeta": "IdTarjeta",
    "idCliente": "IdCliente",
    "idCuenta": "IdCuenta",
    "nombreTarjeta": "NombreTarjeta",
    "estadoActual": "Estado",
    "fechaEmision": "FechaEmision",
}
CAMPOS_ORDEN_HISTORIAL = {
    "idHistorial": "IdHistorial",
    "fechaCambio": "FechaEvento",
}


_SELECT_HISTORIAL = """
    SELECT IdHistorial AS id_historial, IdTarjeta AS id_tarjeta,
           TipoEvento AS tipo_evento, EstadoAnterior AS estado_anterior,
           EstadoActual AS estado_nuevo, Descripcion AS descripcion,
           FechaEvento AS fecha_evento, RealizadoPor AS realizado_por
    FROM Tarjeta.TarjetaHis
"""
_CONTAR_HISTORIAL = "SELECT COUNT(*) FROM Tarjeta.TarjetaHis"
_FILTRO_HISTORIAL = """
    WHERE IdTarjeta = :id_tarjeta
      AND (:fecha_desde IS NULL OR CAST(FechaEvento AS date) >= :fecha_desde)
      AND (:fecha_hasta IS NULL OR CAST(FechaEvento AS date) <= :fecha_hasta)
"""


def _orden(campos: dict[str, str], campo: str, direccion: str, desempate: str) -> str:
    """La clave única como desempate evita filas repetidas entre páginas."""
    columna = campos[campo]
    sentido = "DESC" if direccion == "desc" else "ASC"
    if columna == desempate:
        return f" ORDER BY {columna} {sentido}"
    return f" ORDER BY {columna} {sentido}, {desempate} DESC"


def _rows(
    conn: Connection, sql: str, params: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(text(sql), params or {}).mappings()]


def _one(
    conn: Connection, sql: str, params: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    rows = _rows(conn, sql, params)
    return rows[0] if rows else None


# TAR-01: validaciones previas


def obtener_cuenta(conn: Connection, id_cuenta: int) -> dict[str, Any] | None:
    return _one(
        conn,
        """
        SELECT c.IdCuenta AS id_cuenta, c.IdCliente AS id_cliente,
               c.IdAgencia AS id_agencia, c.Estado AS estado,
               cl.Nombres AS nombres, cl.Apellidos AS apellidos
        FROM Cuentas.Cuenta AS c
        JOIN Clientes.Cliente AS cl ON cl.IdCliente = c.IdCliente
        WHERE c.IdCuenta = :id_cuenta
        """,
        {"id_cuenta": id_cuenta},
    )


def obtener_producto(conn: Connection, id_producto: int) -> dict[str, Any] | None:
    return _one(
        conn,
        """
        SELECT TipoProducto AS tipo_producto, Estado AS estado
        FROM ProductosFinancieros.Producto
        WHERE IdProducto = :id_producto
        """,
        {"id_producto": id_producto},
    )


def obtener_subproducto_con_bin(
    conn: Connection, id_producto: int
) -> dict[str, Any] | None:
    """Primer subproducto activo del producto cuyo BIN también está activo."""
    return _one(
        conn,
        """
        SELECT TOP 1 s.IdSubProducto AS id_sub_producto, b.IdBIN AS id_bin,
               b.CodigoBIN AS codigo_bin
        FROM ProductosFinancieros.SubProducto AS s
        JOIN Tarjeta.BIN AS b ON b.IdBIN = s.IdBIN
        WHERE s.IdProducto = :id_producto AND s.Estado = 'A' AND b.Estado = 'A'
        ORDER BY s.IdSubProducto
        """,
        {"id_producto": id_producto},
    )


def obtener_titular(conn: Connection, id_tarjeta: int) -> dict[str, Any] | None:
    return _one(
        conn,
        """
        SELECT IdCuenta AS id_cuenta, EsExtension AS es_extension, Estado AS estado
        FROM Tarjeta.Tarjeta
        WHERE IdTarjeta = :id_tarjeta
        """,
        {"id_tarjeta": id_tarjeta},
    )


def existe_ciudad(conn: Connection, id_ciudad: int) -> bool:
    return bool(
        _rows(
            conn,
            "SELECT 1 AS existe FROM Catalogo.Ciudad WHERE IdCiudad = :id_ciudad",
            {"id_ciudad": id_ciudad},
        )
    )


# TAR-01: escritura


def insertar_tarjeta(conn: Connection, datos: dict[str, Any]) -> int:
    # La tabla tiene trigger: SQL Server no permite OUTPUT sin INTO
    return conn.execute(
        text(
            """
            SET NOCOUNT ON;
            DECLARE @nuevas TABLE (IdTarjeta int);
            DECLARE @hoy date = CONVERT(
                date, SYSDATETIMEOFFSET() AT TIME ZONE 'SA Pacific Standard Time'
            );
            INSERT INTO Tarjeta.Tarjeta (
                TokenTarjeta, NumeroEnmascarado, HashNumeroTarjeta, NombreTarjeta,
                TipoTarjeta, NombresTitular, ApellidosTitular, IdCliente, IdCuenta,
                IdProducto, IdAgencia, EsExtension, IdTarjetaTitular, FechaEmision,
                FechaExpiracion, PinAsignado, CreadoPor, IdBIN, IdSubProducto, Estado
            )
            OUTPUT INSERTED.IdTarjeta INTO @nuevas
            VALUES (
                :token, :mascara, :hash_pan, :nombre_tarjeta,
                :tipo_tarjeta, :nombres, :apellidos, :id_cliente, :id_cuenta,
                :id_producto, :id_agencia, :es_extension, :id_titular, @hoy,
                DATEADD(year, 5, @hoy), 0, :creado_por, :id_bin, :id_sub_producto,
                'Generada'
            );
            SELECT IdTarjeta FROM @nuevas;
            """
        ),
        datos,
    ).scalar_one()


def insertar_envio(
    conn: Connection,
    id_tarjeta: int,
    id_cliente: int,
    direccion: str,
    id_ciudad: int | None,
) -> None:
    conn.execute(
        text(
            """
            INSERT INTO Tarjeta.EnviosTarjeta
                (IdTarjeta, IdCliente, RequiereEnvio, DireccionEnvio, IdCiudad, Estado)
            VALUES (:id_tarjeta, :id_cliente, 1, :direccion, :id_ciudad, 'PENDIENTE')
            """
        ),
        {
            "id_tarjeta": id_tarjeta,
            "id_cliente": id_cliente,
            "direccion": direccion,
            "id_ciudad": id_ciudad,
        },
    )


def insertar_historial(
    conn: Connection,
    id_tarjeta: int,
    tipo_evento: str,
    estado_anterior: str | None,
    estado_actual: str | None,
    descripcion: str,
    realizado_por: int,
    ip: str | None,
) -> None:
    conn.execute(
        text(
            """
            INSERT INTO Tarjeta.TarjetaHis (
                IdTarjeta, TipoEvento, EstadoAnterior, EstadoActual, Descripcion,
                IdCanal, RealizadoPor, DireccionIP
            )
            VALUES (
                :id_tarjeta, :tipo_evento, :estado_anterior, :estado_actual,
                :descripcion,
                (SELECT IdCanal FROM Canal.Canal WHERE CodigoCanal = 'VENT'),
                :realizado_por, :ip
            )
            """
        ),
        {
            "id_tarjeta": id_tarjeta,
            "tipo_evento": tipo_evento,
            "estado_anterior": estado_anterior,
            "estado_actual": estado_actual,
            "descripcion": descripcion,
            "realizado_por": realizado_por,
            "ip": ip,
        },
    )


# TAR-02 y TAR-03: consultas


def listar_tarjetas(
    conn: Connection,
    id_cliente: int | None,
    id_cuenta: int | None,
    estado: str | None,
    campo: str,
    direccion: str,
    page: int,
    page_size: int,
) -> tuple[list[dict[str, Any]], int]:
    filtros = """
        FROM Tarjeta.Tarjeta
        WHERE (:id_cliente IS NULL OR IdCliente = :id_cliente)
          AND (:id_cuenta IS NULL OR IdCuenta = :id_cuenta)
          AND (:estado IS NULL OR Estado = :estado)
    """
    params: dict[str, Any] = {
        "id_cliente": id_cliente,
        "id_cuenta": id_cuenta,
        "estado": estado,
    }
    total = conn.execute(text("SELECT COUNT(*)" + filtros), params).scalar_one()
    items = _rows(
        conn,
        "SELECT"
        + _COLUMNAS_TARJETA
        + filtros
        + _orden(CAMPOS_ORDEN_TARJETAS, campo, direccion, "IdTarjeta")
        + " OFFSET :saltar ROWS FETCH NEXT :tomar ROWS ONLY",
        {**params, "saltar": (page - 1) * page_size, "tomar": page_size},
    )
    return items, total


def obtener_tarjeta(
    conn: Connection, id_tarjeta: int, bloquear: bool = False
) -> dict[str, Any] | None:
    # UPDLOCK para que dos cambios simultáneos no partan del mismo estado
    desde = " FROM Tarjeta.Tarjeta" + (" WITH (UPDLOCK, ROWLOCK)" if bloquear else "")
    return _one(
        conn,
        "SELECT" + _COLUMNAS_TARJETA + desde + " WHERE IdTarjeta = :id_tarjeta",
        {"id_tarjeta": id_tarjeta},
    )


# TAR-04


def existe_transicion(conn: Connection, origen: str, destino: str) -> bool:
    return bool(
        _rows(
            conn,
            """
            SELECT 1 AS existe FROM Tarjeta.TransicionEstado
            WHERE EstadoOrigen = :origen AND EstadoDestino = :destino
            """,
            {"origen": origen, "destino": destino},
        )
    )


def actualizar_estado(conn: Connection, id_tarjeta: int, estado: str) -> None:
    conn.execute(
        text(
            "UPDATE Tarjeta.Tarjeta SET Estado = :estado WHERE IdTarjeta = :id_tarjeta"
        ),
        {"estado": estado, "id_tarjeta": id_tarjeta},
    )


# TAR-05


def marcar_pin_asignado(conn: Connection, id_tarjeta: int) -> bool:
    """Devuelve False si otra petición asignó el PIN primero."""
    resultado = conn.execute(
        text(
            """
            UPDATE Tarjeta.Tarjeta SET PinAsignado = 1
            WHERE IdTarjeta = :id_tarjeta AND PinAsignado = 0
            """
        ),
        {"id_tarjeta": id_tarjeta},
    )
    return resultado.rowcount == 1


# Repositorio aislado de PAN ficticios (SeguridadDB, solo desarrollo y pruebas)


def guardar_pan_ficticio(
    conn_seguridad: Connection, id_tarjeta: int, cifrado: bytes, referencia: str
) -> None:
    """El PAN llega cifrado por el HSM; nunca se guarda en claro."""
    conn_seguridad.execute(
        text(
            """
            INSERT INTO Pruebas.PanFicticio (IdTarjeta, PanCifrado, ReferenciaClave)
            VALUES (:id_tarjeta, :cifrado, :referencia)
            """
        ),
        {"id_tarjeta": id_tarjeta, "cifrado": cifrado, "referencia": referencia},
    )


def borrar_pan_ficticio(conn_seguridad: Connection, id_tarjeta: int) -> None:
    """Compensación de TAR-01 si la tarjeta no llegó a confirmarse."""
    conn_seguridad.execute(
        text("DELETE FROM Pruebas.PanFicticio WHERE IdTarjeta = :id_tarjeta"),
        {"id_tarjeta": id_tarjeta},
    )


def obtener_pan_ficticio(
    conn_seguridad: Connection, id_tarjeta: int
) -> tuple[bytes, str] | None:
    fila = _one(
        conn_seguridad,
        """
        SELECT PanCifrado AS cifrado, ReferenciaClave AS referencia
        FROM Pruebas.PanFicticio WHERE IdTarjeta = :id_tarjeta
        """,
        {"id_tarjeta": id_tarjeta},
    )
    return None if fila is None else (bytes(fila["cifrado"]), fila["referencia"])


# TAR-05: PIN Offset IBM 3624 en SeguridadDB


def obtener_estado_pin(
    conn_seguridad: Connection, id_tarjeta: int
) -> dict[str, Any] | None:
    """Bloquea la fila hasta el commit: dos asignaciones no se cruzan."""
    return _one(
        conn_seguridad,
        """
        SELECT TienePINAsignado AS confirmado, Estado AS estado,
               CASE WHEN PINOffset IS NULL THEN 0 ELSE 1 END AS tiene_offset
        FROM Tarjetas.TarjetaPIN WITH (UPDLOCK, HOLDLOCK)
        WHERE ID_Tarjeta = :id_tarjeta
        """,
        {"id_tarjeta": id_tarjeta},
    )


def guardar_offset_pendiente(
    conn_seguridad: Connection, id_tarjeta: int, offset: str, referencia_pvk: str
) -> None:
    """Paso 1 de TAR-05: el Offset queda guardado pero el PIN aún no se puede usar."""
    params = {"id_tarjeta": id_tarjeta, "offset": offset, "pvk": referencia_pvk}
    actualizada = conn_seguridad.execute(
        text(
            """
            UPDATE Tarjetas.TarjetaPIN
            SET PINOffset = :offset, ReferenciaClavePVK = :pvk, TienePINAsignado = 0,
                Estado = 'Inactivo', IntentosFallidos = 0,
                FechaAsignacion = CONVERT(
                    datetime, SYSDATETIMEOFFSET() AT TIME ZONE 'SA Pacific Standard Time'
                )
            WHERE ID_Tarjeta = :id_tarjeta
            """
        ),
        params,
    )
    if actualizada.rowcount == 0:
        conn_seguridad.execute(
            text(
                """
                INSERT INTO Tarjetas.TarjetaPIN (
                    ID_Tarjeta, TienePINAsignado, FechaAsignacion, IntentosFallidos,
                    Estado, PINOffset, ReferenciaClavePVK
                )
                VALUES (
                    :id_tarjeta, 0,
                    CONVERT(
                        datetime,
                        SYSDATETIMEOFFSET() AT TIME ZONE 'SA Pacific Standard Time'
                    ),
                    0, 'Inactivo', :offset, :pvk
                )
                """
            ),
            params,
        )


def confirmar_pin(conn_seguridad: Connection, id_tarjeta: int) -> bool:
    """Paso 3 de TAR-05: habilita el PIN. False si no había un Offset pendiente."""
    resultado = conn_seguridad.execute(
        text(
            """
            UPDATE Tarjetas.TarjetaPIN SET TienePINAsignado = 1, Estado = 'Activo'
            WHERE ID_Tarjeta = :id_tarjeta AND PINOffset IS NOT NULL
              AND TienePINAsignado = 0
            """
        ),
        {"id_tarjeta": id_tarjeta},
    )
    return resultado.rowcount == 1


# TAR-06


def existe_tarjeta(conn: Connection, id_tarjeta: int) -> bool:
    return bool(
        _rows(
            conn,
            "SELECT 1 AS existe FROM Tarjeta.Tarjeta WHERE IdTarjeta = :id_tarjeta",
            {"id_tarjeta": id_tarjeta},
        )
    )


def listar_historial(
    conn: Connection,
    id_tarjeta: int,
    fecha_desde: date | None,
    fecha_hasta: date | None,
    campo: str,
    direccion: str,
    page: int,
    page_size: int,
) -> tuple[list[dict[str, Any]], int]:
    params: dict[str, Any] = {
        "id_tarjeta": id_tarjeta,
        "fecha_desde": fecha_desde,
        "fecha_hasta": fecha_hasta,
    }
    total = conn.execute(
        text(_CONTAR_HISTORIAL + _FILTRO_HISTORIAL), params
    ).scalar_one()
    items = _rows(
        conn,
        _SELECT_HISTORIAL
        + _FILTRO_HISTORIAL
        + _orden(CAMPOS_ORDEN_HISTORIAL, campo, direccion, "IdHistorial")
        + " OFFSET :saltar ROWS FETCH NEXT :tomar ROWS ONLY",
        {**params, "saltar": (page - 1) * page_size, "tomar": page_size},
    )
    return items, total
