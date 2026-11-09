from datetime import date
from typing import Any

from sqlalchemy import Connection, text

from app.core.security.pin_version import PinVersionNoDisponible, version_desde_fecha

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
    EsExtension AS es_extension,
    IdTarjetaTitular AS id_tarjeta_titular,
    PinAsignado AS pin_asignado,
    FechaSolicitud AS fecha_solicitud,
    FechaResolucion AS fecha_resolucion,
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
    conn: Connection, id_producto: int, id_sub_producto: int
) -> dict[str, Any] | None:
    """Subproducto elegido, solo si pertenece al producto; con su BIN y estados."""
    return _one(
        conn,
        """
        SELECT s.IdSubProducto AS id_sub_producto, s.Estado AS estado,
               s.CodigoSubProducto AS codigo_sub_producto,
               b.IdBIN AS id_bin, b.CodigoBIN AS codigo_bin, b.Estado AS estado_bin
        FROM ProductosFinancieros.SubProducto AS s
        LEFT JOIN Tarjeta.BIN AS b ON b.IdBIN = s.IdBIN
        WHERE s.IdSubProducto = :id_sub_producto AND s.IdProducto = :id_producto
        """,
        {"id_producto": id_producto, "id_sub_producto": id_sub_producto},
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
                IdProducto, IdAgencia, EsExtension, IdTarjetaTitular, FechaSolicitud,
                FechaEmision, FechaExpiracion, PinAsignado, CreadoPor, IdBIN,
                IdSubProducto, Estado
            )
            OUTPUT INSERTED.IdTarjeta INTO @nuevas
            VALUES (
                :token, :mascara, :hash_pan, :nombre_tarjeta,
                :tipo_tarjeta, :nombres, :apellidos, :id_cliente, :id_cuenta,
                :id_producto, :id_agencia, :es_extension, :id_titular, @hoy,
                -- FechaEmision es obligatoria: provisional hasta pasar a Generada
                @hoy, DATEADD(year, 5, @hoy), 0, :creado_por, :id_bin,
                :id_sub_producto, 'Solicitada'
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
    es_extension: bool | None = None,
) -> tuple[list[dict[str, Any]], int]:
    filtros = """
        FROM Tarjeta.Tarjeta
        WHERE (:id_cliente IS NULL OR IdCliente = :id_cliente)
          AND (:id_cuenta IS NULL OR IdCuenta = :id_cuenta)
          AND (:estado IS NULL OR Estado = :estado)
          AND (:es_extension IS NULL OR EsExtension = :es_extension)
    """
    params: dict[str, Any] = {
        "id_cliente": id_cliente,
        "id_cuenta": id_cuenta,
        "estado": estado,
        "es_extension": es_extension,
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


def actualizar_estado(
    conn: Connection,
    id_tarjeta: int,
    estado: str,
    *,
    resolucion: bool = False,
    emision: bool = False,
    pin_asignado: bool = False,
) -> None:
    """resolucion: FechaResolucion = ahora (aprobación o rechazo).
    emision: FechaEmision = hoy y FechaExpiracion a cinco años (paso a Generada).
    pin_asignado: PinAsignado = 1 (PIN generado al aprobar).

    SQL fijo: las marcas van como parámetros; sin marca, la columna queda igual.
    """
    conn.execute(
        text(
            """
            UPDATE Tarjeta.Tarjeta SET
                Estado = :estado,
                FechaResolucion = CASE WHEN :resolucion = 1
                    THEN CONVERT(datetime2, SYSDATETIMEOFFSET() AT TIME ZONE 'SA Pacific Standard Time')
                    ELSE FechaResolucion END,
                FechaEmision = CASE WHEN :emision = 1
                    THEN CONVERT(date, SYSDATETIMEOFFSET() AT TIME ZONE 'SA Pacific Standard Time')
                    ELSE FechaEmision END,
                FechaExpiracion = CASE WHEN :emision = 1
                    THEN DATEADD(year, 5, CONVERT(date, SYSDATETIMEOFFSET() AT TIME ZONE 'SA Pacific Standard Time'))
                    ELSE FechaExpiracion END,
                PinAsignado = CASE WHEN :pin_asignado = 1 THEN 1 ELSE PinAsignado END
            WHERE IdTarjeta = :id_tarjeta
            """
        ),
        {
            "estado": estado,
            "id_tarjeta": id_tarjeta,
            "resolucion": int(resolucion),
            "emision": int(emision),
            "pin_asignado": int(pin_asignado),
        },
    )


def dias_laborables_desde(conn: Connection, fecha: date) -> int:
    """Días contables (Contabilidad.FechaContable) después de `fecha` y hasta hoy.

    Si el calendario no tiene cargados los días, cuentan como no laborables.
    """
    return conn.execute(
        text(
            """
            SELECT COUNT(*) FROM Contabilidad.FechaContable
            WHERE EsDiaContable = 1 AND Fecha > :fecha
              AND Fecha <= CONVERT(date, SYSDATETIMEOFFSET() AT TIME ZONE 'SA Pacific Standard Time')
            """
        ),
        {"fecha": fecha},
    ).scalar_one()


# TAR-05


def marcar_pin_asignado(conn: Connection, id_tarjeta: int) -> None:
    conn.execute(
        text(
            "UPDATE Tarjeta.Tarjeta SET PinAsignado = 1 WHERE IdTarjeta = :id_tarjeta"
        ),
        {"id_tarjeta": id_tarjeta},
    )


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


# TAR-04 y TAR-05: PIN Offset IBM 3624 en SeguridadDB


def guardar_pin_generado(
    conn_seguridad: Connection,
    id_tarjeta: int,
    offset: str,
    referencia_pvk: str,
    requiere_cambio: bool,
) -> None:
    """Guarda el Offset del PIN que generó el HSM, ya habilitado.

    Reemplaza el anterior: reinicia los intentos y desbloquea el PIN (SEC-ATM-02).
    RequiereCambio = 1 marca un PIN temporal (débito): ATM-01 solo permite cambiarlo.
    """
    if type(id_tarjeta) is not int or id_tarjeta <= 0:
        raise PinVersionNoDisponible("Identificador de asignación no disponible")
    params = {
        "id_tarjeta": id_tarjeta,
        "offset": offset,
        "pvk": referencia_pvk,
        "requiere_cambio": requiere_cambio,
    }
    fecha = conn_seguridad.execute(
        text(
            """
            SET NOCOUNT ON;
            DECLARE @Existe bit = 0, @Anterior datetime, @Asignado bit,
                    @Ahora datetime;
            SELECT @Existe = 1, @Anterior = FechaAsignacion,
                   @Asignado = TienePINAsignado
            FROM Tarjetas.TarjetaPIN WITH (UPDLOCK, HOLDLOCK)
            WHERE ID_Tarjeta = :id_tarjeta AND ID_Tarjeta IS NOT NULL;

            -- Capturar DESPUÉS de adquirir el bloqueo, con precisión datetime.
            SET @Ahora = CONVERT(datetime,
                SYSDATETIMEOFFSET() AT TIME ZONE 'SA Pacific Standard Time');
            IF @Ahora IS NULL OR (@Existe = 1 AND (
                @Ahora <= @Anterior OR (@Anterior IS NULL AND @Asignado = 1)))
            BEGIN
                SELECT CAST(NULL AS datetime) AS FechaAsignacion;
                RETURN;
            END;

            IF @Existe = 1
                UPDATE Tarjetas.TarjetaPIN
                SET PINOffset = :offset, ReferenciaClavePVK = :pvk,
                    TienePINAsignado = 1, Estado = 'Activo', IntentosFallidos = 0,
                    FechaBloqueo = NULL, RequiereCambio = :requiere_cambio,
                    FechaAsignacion = @Ahora
                WHERE ID_Tarjeta = :id_tarjeta;
            ELSE
                INSERT INTO Tarjetas.TarjetaPIN (
                    ID_Tarjeta, TienePINAsignado, FechaAsignacion,
                    IntentosFallidos, Estado, PINOffset,
                    ReferenciaClavePVK, RequiereCambio
                ) VALUES (
                    :id_tarjeta, 1, @Ahora, 0, 'Activo', :offset,
                    :pvk, :requiere_cambio
                );

            SELECT FechaAsignacion FROM Tarjetas.TarjetaPIN
            WHERE ID_Tarjeta = :id_tarjeta;
            """
        ),
        params,
    ).scalar_one()
    if fecha is None:
        raise PinVersionNoDisponible("La fecha de asignación no puede avanzar")
    version_desde_fecha(fecha)


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


def obtener_id_tarjeta_por_hash(conn: Connection, hash_pan: bytes) -> int | None:
    """Resuelve la tarjeta sin enviar el PAN en claro a SQL ni escoger duplicados."""
    id_tarjeta = conn.execute(
        text(
            "SELECT IdTarjeta FROM Tarjeta.Tarjeta WHERE HashNumeroTarjeta = :hash_pan"
        ),
        {"hash_pan": hash_pan},
    ).scalar_one_or_none()
    return None if id_tarjeta is None else int(id_tarjeta)
