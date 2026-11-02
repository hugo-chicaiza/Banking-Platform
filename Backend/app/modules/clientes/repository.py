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
    sql_historial = """
        INSERT INTO Clientes.ClientesHis (
            IdCliente, TipoOperacion, CampoModificado, ValorAnterior,
            ModificadoPor, DireccionIP, FechaModificacion, Observaciones
        )
        VALUES (
            :id_cliente, 'I', 'CREACION', NULL,
            :modificado_por, :direccion_ip, :fecha_modificacion, :observaciones
        );
    """
    conn.execute(
        text(sql_historial),
        {
            "id_cliente": id_cliente,
            "modificado_por": creado_por,
            "direccion_ip": direccion_ip,
            "fecha_modificacion": ahora,
            "observaciones": "Registro inicial de cliente",
        },
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
