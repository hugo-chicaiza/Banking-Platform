from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Connection, text

from app.modules.clientes.schemas import ClienteCreate


def _rows(
    conn: Connection, sql: str, params: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(text(sql), params or {}).mappings()]


def _one(
    conn: Connection, sql: str, params: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    rows = _rows(conn, sql, params)
    return rows[0] if rows else None


def obtener_cliente_por_identificacion(
    conn: Connection, identificacion: str
) -> dict[str, Any] | None:
    """Busca un cliente por su número de identificación.

    Devuelve {id_cliente, estado} o None si no existe.
    """
    return _one(
        conn,
        """
        SELECT IdCliente AS id_cliente,
               Estado    AS estado
        FROM Clientes.Cliente
        WHERE Identificacion = :identificacion
        """,
        {"identificacion": identificacion},
    )


def existe_pais(conn: Connection, codigo_pais: str) -> bool:
    """Verifica si el código de país existe en Catalogo.Paises."""
    return (
        _one(
            conn,
            """
            SELECT 1 AS existe
            FROM Catalogo.Paises
            WHERE CodigoPais = :codigo_pais
            """,
            {"codigo_pais": codigo_pais},
        )
        is not None
    )


def existe_ciudad(conn: Connection, id_ciudad: int, codigo_pais: str) -> bool:
    """Verifica si la ciudad existe y pertenece al país indicado en Catalogo.Ciudad."""
    return (
        _one(
            conn,
            """
            SELECT 1 AS existe
            FROM Catalogo.Ciudad
            WHERE IdCiudad = :id_ciudad AND CodigoPais = :codigo_pais
            """,
            {"id_ciudad": id_ciudad, "codigo_pais": codigo_pais},
        )
        is not None
    )


def existe_actividad_economica(conn: Connection, id_actividad: int) -> bool:
    """Verifica si la actividad económica existe en Catalogo.ActividadEconomica."""
    return (
        _one(
            conn,
            """
            SELECT 1 AS existe
            FROM Catalogo.ActividadEconomica
            WHERE IdActividadEconomica = :id_actividad
            """,
            {"id_actividad": id_actividad},
        )
        is not None
    )


def crear_cliente(
    conn: Connection,
    payload: ClienteCreate,
    creado_por: int,
    direccion_ip: str,
) -> dict[str, Any]:
    """Inserta Cliente, Dirección principal y ClientesHis en una sola transacción."""
    ahora = datetime.now(UTC)
    estado_inicial = "Pendiente"

    # 1. Insertar Clientes.Cliente
    datos_cliente = {
        "identificacion": payload.identificacion,
        "tipo_documento": payload.tipo_documento,
        "tipo_cliente": payload.tipo_cliente,
        "nombres": payload.nombres,
        "apellidos": payload.apellidos,
        "razon_social": payload.razon_social,
        "nombre_comercial": payload.nombre_comercial,
        "id_actividad_economica": payload.id_actividad_economica,
        "fecha_nacimiento": payload.fecha_nacimiento,
        "genero": payload.genero,
        "estado_civil": payload.estado_civil,
        "codigo_pais_nacionalidad": payload.codigo_pais_nacionalidad,
        "telefono_convencional": payload.telefono_convencional,
        "telefono_celular": payload.telefono_celular,
        "email": payload.email,
        "consentimiento_datos": payload.consentimiento_datos,
        "fecha_consentimiento": ahora,
        "estado": estado_inicial,
        "fecha_registro": ahora,
        "creado_por": creado_por,
    }

    sql_cliente = """
        DECLARE @TblCliente TABLE (IdCliente INT);

        INSERT INTO Clientes.Cliente (
            Identificacion, TipoDocumento, TipoCliente, Nombres, Apellidos,
            RazonSocial, NombreComercial, IdActividadEconomica, FechaNacimiento,
            Genero, EstadoCivil, CodigoPaisNacionalidad, TelefonoConvencional,
            TelefonoCelular, Email, ConsentimientoDatos, FechaConsentimiento,
            Estado, FechaRegistro, CreadoPor
        )
        OUTPUT INSERTED.IdCliente INTO @TblCliente
        VALUES (
            :identificacion, :tipo_documento, :tipo_cliente, :nombres, :apellidos,
            :razon_social, :nombre_comercial, :id_actividad_economica, :fecha_nacimiento,
            :genero, :estado_civil, :codigo_pais_nacionalidad, :telefono_convencional,
            :telefono_celular, :email, :consentimiento_datos, :fecha_consentimiento,
            :estado, :fecha_registro, :creado_por
        );

        SELECT IdCliente AS id_cliente FROM @TblCliente;
    """
    row_cliente = _one(
        conn,
        sql_cliente,
        datos_cliente,
    )
    if not row_cliente or "id_cliente" not in row_cliente:
        raise RuntimeError("No se pudo obtener el IdCliente generado tras el INSERT.")

    id_cliente = int(row_cliente["id_cliente"])

    # 2. Insertar Clientes.Direcciones
    dir_payload = payload.direccion
    datos_direccion = {
        "tipo_direccion": dir_payload.tipo_direccion,
        "codigo_pais": dir_payload.codigo_pais,
        "id_ciudad": dir_payload.id_ciudad,
        "sector": dir_payload.sector,
        "calle_direccion": dir_payload.calle_direccion,
        "referencia_ubicacion": dir_payload.referencia_ubicacion,
        "codigo_postal": dir_payload.codigo_postal,
        "es_principal": dir_payload.es_principal,
        "estado": "Activo",
    }
    sql_direccion = """
        DECLARE @TblDireccion TABLE (IdDireccion INT);

        INSERT INTO Clientes.Direcciones (
            IdCliente, TipoDireccion, CodigoPais, IdCiudad, Sector,
            CalleDireccion, ReferenciaUbicacion, CodigoPostal, EsPrincipal,
            Estado, FechaRegistro
        )
        OUTPUT INSERTED.IdDireccion INTO @TblDireccion
        VALUES (
            :id_cliente, :tipo_direccion, :codigo_pais, :id_ciudad, :sector,
            :calle_direccion, :referencia_ubicacion, :codigo_postal, :es_principal,
            :estado, :fecha_registro
        );

        SELECT IdDireccion AS id_direccion FROM @TblDireccion;
    """
    row_direccion = _one(
        conn,
        sql_direccion,
        {
            "id_cliente": id_cliente,
            **datos_direccion,
            "fecha_registro": ahora,
        },
    )
    id_direccion = (
        int(row_direccion["id_direccion"])
        if row_direccion and "id_direccion" in row_direccion
        else 1
    )

    # 3. Insertar Clientes.ClientesHis (TipoOperacion = 'I')
    _insertar_historial(
        conn,
        id_cliente=id_cliente,
        tipo_operacion="I",
        campo="CREACION",
        valor_anterior=None,
        modificado_por=creado_por,
        direccion_ip=direccion_ip,
        observaciones="Registro inicial de cliente",
    )

    direccion_dict = {
        "id_direccion": id_direccion,
        **datos_direccion,
    }

    return {
        "id_cliente": id_cliente,
        **datos_cliente,
        "direcciones": [direccion_dict],
    }


# ---------------------------------------------------------------------------
# Helpers de auditoría
# ---------------------------------------------------------------------------


def _insertar_historial(
    conn: Connection,
    *,
    id_cliente: int,
    tipo_operacion: str,
    campo: str,
    valor_anterior: str | None,
    modificado_por: int,
    direccion_ip: str,
    observaciones: str,
) -> None:
    """Inserta una fila en Clientes.ClientesHis."""
    conn.execute(
        text("""
            INSERT INTO Clientes.ClientesHis (
                IdCliente, TipoOperacion, CampoModificado, ValorAnterior,
                ModificadoPor, DireccionIP, FechaModificacion, Observaciones
            )
            VALUES (
                :id_cliente, :tipo_operacion, :campo, :valor_anterior,
                :modificado_por, :direccion_ip, :fecha_modificacion, :observaciones
            );
        """),
        {
            "id_cliente": id_cliente,
            "tipo_operacion": tipo_operacion,
            "campo": campo,
            "valor_anterior": valor_anterior,
            "modificado_por": modificado_por,
            "direccion_ip": direccion_ip,
            "fecha_modificacion": datetime.now(UTC),
            "observaciones": observaciones,
        },
    )


# ---------------------------------------------------------------------------
# Direcciones del cliente
# ---------------------------------------------------------------------------

_SQL_DIRECCION_COLUMNS = """
    IdDireccion          AS id_direccion,
    TipoDireccion        AS tipo_direccion,
    CodigoPais           AS codigo_pais,
    IdCiudad             AS id_ciudad,
    Sector               AS sector,
    CalleDireccion       AS calle_direccion,
    ReferenciaUbicacion  AS referencia_ubicacion,
    CodigoPostal         AS codigo_postal,
    EsPrincipal          AS es_principal,
    Estado               AS estado
"""


def obtener_cliente_por_id(conn: Connection, id_cliente: int) -> dict[str, Any] | None:
    """Retorna {id_cliente, estado} o None si no existe."""
    return _one(
        conn,
        """
        SELECT IdCliente AS id_cliente,
               Estado    AS estado
        FROM Clientes.Cliente
        WHERE IdCliente = :id_cliente
        """,
        {"id_cliente": id_cliente},
    )


def listar_direcciones(conn: Connection, id_cliente: int) -> list[dict[str, Any]]:
    """Direcciones Activo/Inactivo del cliente, principal primero (CLI-09)."""
    return _rows(
        conn,
        f"""
        SELECT {_SQL_DIRECCION_COLUMNS}
        FROM Clientes.Direcciones
        WHERE IdCliente = :id_cliente
          AND Estado IN ('Activo', 'Inactivo')
        ORDER BY EsPrincipal DESC, IdDireccion ASC
        """,
        {"id_cliente": id_cliente},
    )


def _desmarcar_principal(conn: Connection, id_cliente: int) -> None:
    """Pone EsPrincipal = 0 en la dirección principal activa del cliente."""
    conn.execute(
        text("""
            UPDATE Clientes.Direcciones
            SET EsPrincipal = 0
            WHERE IdCliente = :id_cliente
              AND EsPrincipal = 1
              AND Estado = 'Activo'
        """),
        {"id_cliente": id_cliente},
    )


def insertar_direccion(
    conn: Connection,
    id_cliente: int,
    datos: dict[str, Any],
    *,
    modificado_por: int,
    direccion_ip: str,
) -> dict[str, Any]:
    """Inserta una dirección y registra historial (CLI-10).

    Si es_principal, desmarca la anterior primero.
    Retorna el dict de la dirección creada.
    """
    if datos.get("es_principal"):
        _desmarcar_principal(conn, id_cliente)

    ahora = datetime.now(UTC)
    sql = f"""
        DECLARE @TblDir TABLE (IdDireccion INT);

        INSERT INTO Clientes.Direcciones (
            IdCliente, TipoDireccion, CodigoPais, IdCiudad, Sector,
            CalleDireccion, ReferenciaUbicacion, CodigoPostal, EsPrincipal,
            Estado, FechaRegistro
        )
        OUTPUT INSERTED.IdDireccion INTO @TblDir
        VALUES (
            :id_cliente, :tipo_direccion, :codigo_pais, :id_ciudad, :sector,
            :calle_direccion, :referencia_ubicacion, :codigo_postal, :es_principal,
            :estado, :fecha_registro
        );

        SELECT {_SQL_DIRECCION_COLUMNS}
        FROM Clientes.Direcciones
        WHERE IdDireccion = (SELECT TOP 1 IdDireccion FROM @TblDir);
    """
    params = {
        "id_cliente": id_cliente,
        "tipo_direccion": datos["tipo_direccion"],
        "codigo_pais": datos["codigo_pais"],
        "id_ciudad": datos["id_ciudad"],
        "sector": datos.get("sector"),
        "calle_direccion": datos["calle_direccion"],
        "referencia_ubicacion": datos["referencia_ubicacion"],
        "codigo_postal": datos.get("codigo_postal"),
        "es_principal": datos.get("es_principal", False),
        "estado": "Activo",
        "fecha_registro": ahora,
    }
    row = _one(conn, sql, params)
    if not row:
        raise RuntimeError("No se pudo obtener la dirección insertada.")

    _insertar_historial(
        conn,
        id_cliente=id_cliente,
        tipo_operacion="I",
        campo="DIRECCION",
        valor_anterior=None,
        modificado_por=modificado_por,
        direccion_ip=direccion_ip,
        observaciones=f"Dirección {row['id_direccion']} creada",
    )

    return row


def obtener_direccion(
    conn: Connection, id_cliente: int, id_direccion: int
) -> dict[str, Any] | None:
    """Retorna la dirección si pertenece al cliente, o None."""
    return _one(
        conn,
        f"""
        SELECT {_SQL_DIRECCION_COLUMNS}
        FROM Clientes.Direcciones
        WHERE IdDireccion = :id_direccion
          AND IdCliente = :id_cliente
        """,
        {"id_direccion": id_direccion, "id_cliente": id_cliente},
    )


def actualizar_direccion(
    conn: Connection,
    id_cliente: int,
    id_direccion: int,
    cambios: dict[str, Any],
    *,
    modificado_por: int,
    direccion_ip: str,
    valores_anteriores: dict[str, Any],
) -> dict[str, Any]:
    """Actualiza campos de una dirección y registra historial

    Si es_principal pasa a True, desmarca la anterior.
    Retorna el dict actualizado.
    """
    if cambios.get("es_principal"):
        _desmarcar_principal(conn, id_cliente)

    # Mapa snake_case → columna SQL
    col_map: dict[str, str] = {
        "tipo_direccion": "TipoDireccion",
        "codigo_pais": "CodigoPais",
        "id_ciudad": "IdCiudad",
        "sector": "Sector",
        "calle_direccion": "CalleDireccion",
        "referencia_ubicacion": "ReferenciaUbicacion",
        "codigo_postal": "CodigoPostal",
        "es_principal": "EsPrincipal",
    }

    sets: list[str] = []
    params: dict[str, Any] = {
        "id_direccion": id_direccion,
        "id_cliente": id_cliente,
    }
    for campo, valor in cambios.items():
        col = col_map[campo]
        sets.append(f"{col} = :{campo}")
        params[campo] = valor

    if not sets:
        row = obtener_direccion(conn, id_cliente, id_direccion)
        if not row:
            raise RuntimeError("Dirección no encontrada tras actualizar.")
        return row

    sql = f"""
        UPDATE Clientes.Direcciones
        SET {", ".join(sets)}
        WHERE IdDireccion = :id_direccion AND IdCliente = :id_cliente;

        SELECT {_SQL_DIRECCION_COLUMNS}
        FROM Clientes.Direcciones
        WHERE IdDireccion = :id_direccion AND IdCliente = :id_cliente;
    """
    row = _one(conn, sql, params)
    if not row:
        raise RuntimeError("Dirección no encontrada tras actualizar.")

    # Registrar cada cambio en historial
    for campo in cambios:
        _insertar_historial(
            conn,
            id_cliente=id_cliente,
            tipo_operacion="U",
            campo=f"DIRECCION.{campo}",
            valor_anterior=str(valores_anteriores.get(campo)),
            modificado_por=modificado_por,
            direccion_ip=direccion_ip,
            observaciones=f"Dirección {id_direccion} actualizada: {campo}",
        )

    return row


def eliminar_direccion_logica(
    conn: Connection, id_cliente: int, id_direccion: int
) -> None:
    """Baja lógica: Estado = 'Eliminado' (CLI-12)."""
    conn.execute(
        text("""
            UPDATE Clientes.Direcciones
            SET Estado = 'Eliminado'
            WHERE IdDireccion = :id_direccion
              AND IdCliente = :id_cliente
        """),
        {"id_direccion": id_direccion, "id_cliente": id_cliente},
    )
