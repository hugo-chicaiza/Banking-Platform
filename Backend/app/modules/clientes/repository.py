import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Connection, bindparam, text

from app.core.api.errors import problema
from app.modules.clientes.schemas import ClienteCreate

CAMPOS_EDICION_CLIENTE = {
    "nombres": "Nombres",
    "apellidos": "Apellidos",
    "razon_social": "RazonSocial",
    "nombre_comercial": "NombreComercial",
    "id_actividad_economica": "IdActividadEconomica",
    "estado_civil": "EstadoCivil",
    "telefono_convencional": "TelefonoConvencional",
    "telefono_celular": "TelefonoCelular",
    "email": "Email",
}


def observaciones_cambio(valor_anterior: Any, valor_nuevo: Any, motivo: str) -> str:
    """JSON ASCII: len coincide con bytes de VARCHAR; nunca se trunca."""
    valor = json.dumps(
        {
            "v": 1,
            "valorAnterior": valor_anterior,
            "valorNuevo": valor_nuevo,
            "motivo": motivo,
        },
        ensure_ascii=True,
        separators=(",", ":"),
    )
    if len(valor) > 500:
        raise problema(
            422,
            "AUDITORIA_EXCEDE_LIMITE",
            "El cambio y su motivo exceden la capacidad del historial.",
        )
    return valor


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
        SET NOCOUNT ON;
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
        SET NOCOUNT ON;
        DECLARE @TblDireccion TABLE (IdDireccion INT);

        INSERT INTO Clientes.Direcciones (
            IdCliente, TipoDireccion, IdCiudad, Sector,
            CalleDireccion, ReferenciaUbicacion, CodigoPostal, EsPrincipal,
            Estado, FechaRegistro, CreadoPor
        )
        OUTPUT INSERTED.IdDireccion INTO @TblDireccion
        VALUES (
            :id_cliente, :tipo_direccion, :id_ciudad, :sector,
            :calle_direccion, :referencia_ubicacion, :codigo_postal, :es_principal,
            :estado, :fecha_registro, :creado_por
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
            "creado_por": creado_por,
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
    """Compatibilidad de los endpoints existentes con el esquema Snap_* real."""
    insertar_historial_cliente(
        conn,
        id_cliente=id_cliente,
        tipo_operacion=tipo_operacion,
        campo=campo,
        modificado_por=modificado_por,
        direccion_ip=direccion_ip,
        observaciones=(
            observaciones
            if valor_anterior is None
            else observaciones_cambio(valor_anterior, None, observaciones)
        ),
    )


def insertar_historial_cliente(
    conn: Connection,
    *,
    id_cliente: int,
    tipo_operacion: str,
    campo: str,
    modificado_por: int,
    direccion_ip: str,
    observaciones: str,
) -> None:
    """Inserta solo columnas existentes; misma transacción que el cliente."""
    conn.execute(
        text("""
            INSERT INTO Clientes.ClientesHis (
                IdCliente, TipoOperacion, CampoModificado,
                ModificadoPor, DireccionIP, FechaModificacion, Observaciones
            )
            VALUES (
                :id_cliente, :tipo_operacion, :campo,
                :modificado_por, :direccion_ip, :fecha_modificacion, :observaciones
            );
        """),
        {
            "id_cliente": id_cliente,
            "tipo_operacion": tipo_operacion,
            "campo": campo,
            "modificado_por": modificado_por,
            "direccion_ip": direccion_ip,
            "fecha_modificacion": datetime.now(UTC),
            "observaciones": observaciones,
        },
    )


# ---------------------------------------------------------------------------
# CLI-09..CLI-12 · Direcciones del cliente
# ---------------------------------------------------------------------------


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


def _direcciones_por_clientes(
    conn: Connection, ids_clientes: list[int], *, solo_activas: bool
) -> list[dict[str, Any]]:
    """Carga las direcciones de toda la página en una sola consulta."""
    if not ids_clientes:
        return []
    sql = text("""
        SELECT IdCliente            AS id_cliente,
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
        FROM Clientes.Direcciones
        WHERE IdCliente IN :ids_clientes
          AND Estado IN ('Activo', 'Inactivo')
          AND (:solo_activas = 0 OR Estado = 'Activo')
        ORDER BY IdCliente, EsPrincipal DESC, IdDireccion ASC
        """).bindparams(bindparam("ids_clientes", expanding=True))
    return [
        dict(row)
        for row in conn.execute(
            sql, {"ids_clientes": ids_clientes, "solo_activas": solo_activas}
        ).mappings()
    ]


def listar_direcciones(conn: Connection, id_cliente: int) -> list[dict[str, Any]]:
    """Direcciones Activo/Inactivo del cliente, principal primero (CLI-09)."""
    return _direcciones_por_clientes(conn, [id_cliente], solo_activas=False)


def consultar_clientes(
    conn: Connection,
    *,
    id_cliente: int | None = None,
    q: str | None = None,
    identificacion: str | None = None,
    tipo_cliente: str | None = None,
    estado: str | None = None,
    page: int = 1,
    page_size: int = 20,
    campo: str = "IdCliente",
    direccion: str = "asc",
    solo_direcciones_activas: bool = False,
) -> tuple[list[dict[str, Any]], int]:
    """Consulta compartida por listado y detalle, con total aun fuera de página.

    El LEFT JOIN conserva el conteo cuando la página no contiene clientes.
    ROW_NUMBER agrega IdCliente como desempate para una paginación estable.
    """
    filas = _rows(
        conn,
        """
        WITH Filtrados AS (
            SELECT IdCliente AS id_cliente, Identificacion AS identificacion,
                   TipoDocumento AS tipo_documento, TipoCliente AS tipo_cliente,
                   Nombres AS nombres, Apellidos AS apellidos,
                   RazonSocial AS razon_social, NombreComercial AS nombre_comercial,
                   IdActividadEconomica AS id_actividad_economica,
                   FechaNacimiento AS fecha_nacimiento, Genero AS genero,
                   EstadoCivil AS estado_civil,
                   CodigoPaisNacionalidad AS codigo_pais_nacionalidad,
                   TelefonoConvencional AS telefono_convencional,
                   TelefonoCelular AS telefono_celular, Email AS email,
                   ConsentimientoDatos AS consentimiento_datos,
                   FechaConsentimiento AS fecha_consentimiento,
                   Estado AS estado, FechaRegistro AS fecha_registro,
                   CreadoPor AS creado_por,
                   ROW_NUMBER() OVER (ORDER BY
                       CASE WHEN :campo = 'IdCliente' AND :direccion = 'asc'
                            THEN IdCliente END ASC,
                       CASE WHEN :campo = 'IdCliente' AND :direccion = 'desc'
                            THEN IdCliente END DESC,
                       CASE WHEN :campo = 'Identificacion' AND :direccion = 'asc'
                            THEN Identificacion END ASC,
                       CASE WHEN :campo = 'Identificacion' AND :direccion = 'desc'
                            THEN Identificacion END DESC,
                       CASE WHEN :campo = 'TipoCliente' AND :direccion = 'asc'
                            THEN TipoCliente END ASC,
                       CASE WHEN :campo = 'TipoCliente' AND :direccion = 'desc'
                            THEN TipoCliente END DESC,
                       CASE WHEN :campo = 'Nombres' AND :direccion = 'asc'
                            THEN Nombres END ASC,
                       CASE WHEN :campo = 'Nombres' AND :direccion = 'desc'
                            THEN Nombres END DESC,
                       CASE WHEN :campo = 'Apellidos' AND :direccion = 'asc'
                            THEN Apellidos END ASC,
                       CASE WHEN :campo = 'Apellidos' AND :direccion = 'desc'
                            THEN Apellidos END DESC,
                       CASE WHEN :campo = 'RazonSocial' AND :direccion = 'asc'
                            THEN RazonSocial END ASC,
                       CASE WHEN :campo = 'RazonSocial' AND :direccion = 'desc'
                            THEN RazonSocial END DESC,
                       CASE WHEN :campo = 'Estado' AND :direccion = 'asc'
                            THEN Estado END ASC,
                       CASE WHEN :campo = 'Estado' AND :direccion = 'desc'
                            THEN Estado END DESC,
                       CASE WHEN :campo = 'FechaRegistro' AND :direccion = 'asc'
                            THEN FechaRegistro END ASC,
                       CASE WHEN :campo = 'FechaRegistro' AND :direccion = 'desc'
                            THEN FechaRegistro END DESC,
                       IdCliente ASC
                   ) AS numero_fila
            FROM Clientes.Cliente
            WHERE (:id_cliente IS NULL OR IdCliente = :id_cliente)
              AND (:identificacion IS NULL OR Identificacion = :identificacion)
              AND (:tipo_cliente IS NULL OR TipoCliente = :tipo_cliente)
              AND (:estado IS NULL OR Estado = :estado)
              AND (:q_like IS NULL OR (
                  Identificacion LIKE :q_like OR Nombres LIKE :q_like
                  OR Apellidos LIKE :q_like OR RazonSocial LIKE :q_like
              ))
        )
        SELECT p.*, t.total
        FROM (SELECT COUNT(*) AS total FROM Filtrados) AS t
        LEFT JOIN Filtrados AS p
          ON p.numero_fila > :offset AND p.numero_fila <= :limite
        ORDER BY p.numero_fila
        """,
        {
            "id_cliente": id_cliente,
            "q_like": None if q is None else f"%{q}%",
            "identificacion": identificacion,
            "tipo_cliente": tipo_cliente,
            "estado": estado,
            "campo": campo,
            "direccion": direccion,
            "offset": (page - 1) * page_size,
            "limite": page * page_size,
        },
    )
    total = int(filas[0]["total"]) if filas else 0
    clientes = [fila for fila in filas if fila["id_cliente"] is not None]
    direcciones: dict[int, list[dict[str, Any]]] = {}
    for row in _direcciones_por_clientes(
        conn,
        [c["id_cliente"] for c in clientes],
        solo_activas=solo_direcciones_activas,
    ):
        direcciones.setdefault(row["id_cliente"], []).append(row)
    for cliente in clientes:
        cliente["direcciones"] = direcciones.get(cliente["id_cliente"], [])
    return clientes, total


def obtener_cliente_detalle(conn: Connection, id_cliente: int) -> dict[str, Any] | None:
    filas, _ = consultar_clientes(
        conn, id_cliente=id_cliente, page_size=1, solo_direcciones_activas=True
    )
    return filas[0] if filas else None


def bloquear_cliente(conn: Connection, id_cliente: int) -> dict[str, Any] | None:
    """Bloqueo de actualización hasta commit/rollback, también con RCSI."""
    return _one(
        conn,
        """
        SELECT IdCliente AS id_cliente, Estado AS estado
        FROM Clientes.Cliente WITH (UPDLOCK, HOLDLOCK)
        WHERE IdCliente = :id_cliente
    """,
        {"id_cliente": id_cliente},
    )


def actualizar_cliente(
    conn: Connection, id_cliente: int, cambios: dict[str, Any]
) -> None:
    params: dict[str, Any] = {"id_cliente": id_cliente}
    for campo in CAMPOS_EDICION_CLIENTE:
        params[campo] = cambios.get(campo)
        params["enviado_" + campo] = campo in cambios
    conn.execute(
        text("""
        UPDATE Clientes.Cliente
        SET Nombres = CASE WHEN :enviado_nombres = 1 THEN :nombres ELSE Nombres END,
            Apellidos = CASE WHEN :enviado_apellidos = 1 THEN :apellidos ELSE Apellidos END,
            RazonSocial = CASE WHEN :enviado_razon_social = 1 THEN :razon_social ELSE RazonSocial END,
            NombreComercial = CASE WHEN :enviado_nombre_comercial = 1 THEN :nombre_comercial ELSE NombreComercial END,
            IdActividadEconomica = CASE WHEN :enviado_id_actividad_economica = 1 THEN :id_actividad_economica ELSE IdActividadEconomica END,
            EstadoCivil = CASE WHEN :enviado_estado_civil = 1 THEN :estado_civil ELSE EstadoCivil END,
            TelefonoConvencional = CASE WHEN :enviado_telefono_convencional = 1 THEN :telefono_convencional ELSE TelefonoConvencional END,
            TelefonoCelular = CASE WHEN :enviado_telefono_celular = 1 THEN :telefono_celular ELSE TelefonoCelular END,
            Email = CASE WHEN :enviado_email = 1 THEN :email ELSE Email END
        WHERE IdCliente = :id_cliente
    """),
        params,
    )


def actualizar_estado_cliente(conn: Connection, id_cliente: int, estado: str) -> None:
    conn.execute(
        text("""
        UPDATE Clientes.Cliente SET Estado = :estado WHERE IdCliente = :id_cliente
    """),
        {"id_cliente": id_cliente, "estado": estado},
    )


def cuentas_para_cambio_estado(
    conn: Connection, id_cliente: int
) -> list[dict[str, Any]]:
    return _rows(
        conn,
        """
        SELECT Estado AS estado, Saldo AS saldo, SaldoRetenido AS saldo_retenido
        FROM Cuentas.Cuenta WITH (UPDLOCK, HOLDLOCK)
        WHERE IdCliente = :id_cliente
    """,
        {"id_cliente": id_cliente},
    )


def desembolsos_para_cambio_estado(
    conn: Connection, id_cliente: int
) -> list[dict[str, Any]]:
    # Se lee el rango completo: también bloquea nuevos desembolsos del cliente.
    return _rows(
        conn,
        """
        SELECT IdSolicitud AS id_solicitud, Estado AS estado
        FROM Credito.CreditoDesembolso WITH (UPDLOCK, HOLDLOCK)
        WHERE IdCliente = :id_cliente
    """,
        {"id_cliente": id_cliente},
    )


def resumen_para_cambio_estado(
    conn: Connection, id_solicitud: int
) -> list[dict[str, Any]]:
    return _rows(
        conn,
        """
        SELECT Version AS version, NumeroTotalCuotas AS numero_total_cuotas
        FROM Credito.CreditoResumen WITH (UPDLOCK, HOLDLOCK)
        WHERE IdSolicitud = :id_solicitud AND EsVigente = 1
    """,
        {"id_solicitud": id_solicitud},
    )


def cuotas_para_cambio_estado(
    conn: Connection, id_solicitud: int
) -> list[dict[str, Any]]:
    """Cuotas del plan vigente, pagos y mora; no usa Estado de la solicitud."""
    return _rows(
        conn,
        """
        SELECT p.IdPlanCuota AS id_plan_cuota, p.Version AS version,
               p.Numero AS numero, c.IdCuota AS id_cuota, c.Estado AS estado,
               c.CapitalOriginal - c.CapitalAbonado AS capital_pendiente,
               c.Interes AS interes, c.TotalSeguros AS seguros,
               c.TotalImpuestos AS impuestos,
               pg.capital_pagado, pg.interes_pagado, pg.seguros_pagados,
               pg.impuestos_pagados,
               COALESCE(m.mora_pendiente, 0) AS mora_pendiente
        FROM Credito.CreditoPlanAmortizacion AS p WITH (UPDLOCK, HOLDLOCK)
        LEFT JOIN Credito.CreditoCuota AS c WITH (UPDLOCK, HOLDLOCK)
          ON c.IdPlanCuota = p.IdPlanCuota AND c.IdSolicitud = p.IdSolicitud
        OUTER APPLY (
            SELECT SUM(Capital) AS capital_pagado, SUM(Interes) AS interes_pagado,
                   SUM(TotalSeguros) AS seguros_pagados, SUM(TotalImpuestos) AS impuestos_pagados
            FROM Credito.CreditoCuotaPago WITH (UPDLOCK, HOLDLOCK)
            WHERE IdCuota = c.IdCuota
        ) AS pg
        OUTER APPLY (
            SELECT SUM(RecargoMora) AS mora_pendiente
            FROM Credito.CreditoCuotaMora AS mora WITH (UPDLOCK, HOLDLOCK)
            JOIN Credito.CreditoCuota AS cuota_mora WITH (UPDLOCK, HOLDLOCK)
              ON cuota_mora.IdCuota = mora.IdCuota
            WHERE cuota_mora.IdSolicitud = p.IdSolicitud AND mora.Liquidada = 0
        ) AS m
        WHERE p.IdSolicitud = :id_solicitud AND p.EsVigente = 1
        ORDER BY p.Numero, p.IdPlanCuota
    """,
        {"id_solicitud": id_solicitud},
    )


def listar_historial_cliente(
    conn: Connection,
    id_cliente: int,
    *,
    page: int,
    page_size: int,
    campo: str,
    direccion: str,
) -> tuple[list[dict[str, Any]], int]:
    """SQL estático; el servicio lee valorAnterior del JSON versionado."""
    filas = _rows(
        conn,
        """
        WITH Historial AS (
            SELECT IdHistorial AS id_historial, TipoOperacion AS tipo_operacion,
                   CampoModificado AS campo_modificado,
                   ModificadoPor AS modificado_por, DireccionIP AS direccion_ip,
                   FechaModificacion AS fecha_modificacion, Observaciones AS observaciones,
                   ROW_NUMBER() OVER (ORDER BY
                       CASE WHEN :campo = 'IdHistorial' AND :direccion = 'asc'
                            THEN IdHistorial END ASC,
                       CASE WHEN :campo = 'IdHistorial' AND :direccion = 'desc'
                            THEN IdHistorial END DESC,
                       CASE WHEN :campo = 'FechaModificacion' AND :direccion = 'asc'
                            THEN FechaModificacion END ASC,
                       CASE WHEN :campo = 'FechaModificacion' AND :direccion = 'desc'
                            THEN FechaModificacion END DESC,
                       CASE WHEN :campo = 'TipoOperacion' AND :direccion = 'asc'
                            THEN TipoOperacion END ASC,
                       CASE WHEN :campo = 'TipoOperacion' AND :direccion = 'desc'
                            THEN TipoOperacion END DESC,
                       CASE WHEN :campo = 'CampoModificado' AND :direccion = 'asc'
                            THEN CampoModificado END ASC,
                       CASE WHEN :campo = 'CampoModificado' AND :direccion = 'desc'
                            THEN CampoModificado END DESC,
                       CASE WHEN :campo = 'ModificadoPor' AND :direccion = 'asc'
                            THEN ModificadoPor END ASC,
                       CASE WHEN :campo = 'ModificadoPor' AND :direccion = 'desc'
                            THEN ModificadoPor END DESC,
                       IdHistorial DESC
                   ) AS numero_fila
            FROM Clientes.ClientesHis
            WHERE IdCliente = :id_cliente
        )
        SELECT p.*, t.total
        FROM (SELECT COUNT(*) AS total FROM Historial) AS t
        LEFT JOIN Historial AS p
          ON p.numero_fila > :offset AND p.numero_fila <= :limite
        ORDER BY p.numero_fila
        """,
        {
            "id_cliente": id_cliente,
            "campo": campo,
            "direccion": direccion,
            "offset": (page - 1) * page_size,
            "limite": page * page_size,
        },
    )
    total = int(filas[0]["total"]) if filas else 0
    return [fila for fila in filas if fila["id_historial"] is not None], total


def listar_cuentas_perfil(conn: Connection, id_cliente: int) -> list[dict[str, Any]]:
    return _rows(
        conn,
        """
        SELECT c.IdCuenta AS id_cuenta, c.NumeroCuenta AS numero_cuenta,
               c.IdCliente AS id_cliente, c.IdAgencia AS id_agencia,
               c.IdProducto AS id_producto, p.TipoCuenta AS tipo_cuenta,
               c.Saldo AS saldo, c.SaldoRetenido AS saldo_retenido,
               c.Saldo - c.SaldoRetenido AS saldo_disponible,
               c.Estado AS estado, c.FechaApertura AS fecha_apertura,
               c.FechaUltimoMovimiento AS fecha_ultimo_movimiento,
               c.FechaCierre AS fecha_cierre
        FROM Cuentas.Cuenta AS c
        INNER JOIN ProductosFinancieros.Producto AS p
          ON p.IdProducto = c.IdProducto
        WHERE c.IdCliente = :id_cliente
        ORDER BY c.IdCuenta
        """,
        {"id_cliente": id_cliente},
    )


def listar_tarjetas_perfil(conn: Connection, id_cliente: int) -> list[dict[str, Any]]:
    return _rows(
        conn,
        """
        SELECT IdTarjeta AS id_tarjeta, TokenTarjeta AS token_tarjeta,
               RTRIM(NumeroEnmascarado) AS numero_enmascarado,
               TipoTarjeta AS tipo_tarjeta, NombreTarjeta AS nombre_tarjeta,
               IdCliente AS id_cliente, IdCuenta AS id_cuenta,
               IdProducto AS id_producto, Estado AS estado_actual,
               EsExtension AS es_extension, IdTarjetaTitular AS id_tarjeta_titular,
               PinAsignado AS pin_asignado, FechaEmision AS fecha_emision,
               FechaExpiracion AS fecha_expiracion
        FROM Tarjeta.Tarjeta
        WHERE IdCliente = :id_cliente
        ORDER BY IdTarjeta
        """,
        {"id_cliente": id_cliente},
    )


def listar_creditos_perfil(conn: Connection, id_cliente: int) -> list[dict[str, Any]]:
    """Conserva solicitudes que todavía no tienen un resumen de desembolso."""
    return _rows(
        conn,
        """
        SELECT s.IdSolicitud AS id_solicitud, s.NumeroSolicitud AS numero_solicitud,
               t.Nombre AS tipo_credito, r.MontoDesembolsado AS monto_desembolsado,
               r.SaldoCapital AS saldo_capital, r.ProximoVencimiento AS proxima_cuota,
               s.Estado AS estado
        FROM Credito.CreditoSolicitud AS s
        JOIN Credito.TipoCredito AS t ON t.IdTipoCredito = s.IdTipoCredito
        LEFT JOIN Credito.CreditoResumen AS r ON r.IdSolicitud = s.IdSolicitud
        WHERE s.IdCliente = :id_cliente
        ORDER BY s.IdSolicitud
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
    sql = """
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

        SELECT IdDireccion          AS id_direccion,
               TipoDireccion        AS tipo_direccion,
               CodigoPais           AS codigo_pais,
               IdCiudad             AS id_ciudad,
               Sector               AS sector,
               CalleDireccion       AS calle_direccion,
               ReferenciaUbicacion  AS referencia_ubicacion,
               CodigoPostal         AS codigo_postal,
               EsPrincipal          AS es_principal,
               Estado               AS estado
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
        """
        SELECT IdDireccion          AS id_direccion,
               TipoDireccion        AS tipo_direccion,
               CodigoPais           AS codigo_pais,
               IdCiudad             AS id_ciudad,
               Sector               AS sector,
               CalleDireccion       AS calle_direccion,
               ReferenciaUbicacion  AS referencia_ubicacion,
               CodigoPostal         AS codigo_postal,
               EsPrincipal          AS es_principal,
               Estado               AS estado
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
    """Actualiza campos de una dirección y registra historial (CLI-11).

    Si es_principal pasa a True, desmarca la anterior.
    Retorna el dict actualizado.
    """
    if cambios.get("es_principal"):
        _desmarcar_principal(conn, id_cliente)

    params: dict[str, Any] = {
        "id_direccion": id_direccion,
        "id_cliente": id_cliente,
        "tipo_direccion": cambios.get(
            "tipo_direccion", valores_anteriores["tipo_direccion"]
        ),
        "codigo_pais": cambios.get("codigo_pais", valores_anteriores["codigo_pais"]),
        "id_ciudad": cambios.get("id_ciudad", valores_anteriores["id_ciudad"]),
        "sector": cambios.get("sector", valores_anteriores.get("sector")),
        "calle_direccion": cambios.get(
            "calle_direccion", valores_anteriores["calle_direccion"]
        ),
        "referencia_ubicacion": cambios.get(
            "referencia_ubicacion", valores_anteriores["referencia_ubicacion"]
        ),
        "codigo_postal": cambios.get(
            "codigo_postal", valores_anteriores.get("codigo_postal")
        ),
        "es_principal": cambios.get("es_principal", valores_anteriores["es_principal"]),
    }

    sql = """
        UPDATE Clientes.Direcciones
        SET TipoDireccion = :tipo_direccion,
            CodigoPais = :codigo_pais,
            IdCiudad = :id_ciudad,
            Sector = :sector,
            CalleDireccion = :calle_direccion,
            ReferenciaUbicacion = :referencia_ubicacion,
            CodigoPostal = :codigo_postal,
            EsPrincipal = :es_principal
        WHERE IdDireccion = :id_direccion AND IdCliente = :id_cliente;

        SELECT IdDireccion          AS id_direccion,
               TipoDireccion        AS tipo_direccion,
               CodigoPais           AS codigo_pais,
               IdCiudad             AS id_ciudad,
               Sector               AS sector,
               CalleDireccion       AS calle_direccion,
               ReferenciaUbicacion  AS referencia_ubicacion,
               CodigoPostal         AS codigo_postal,
               EsPrincipal          AS es_principal,
               Estado               AS estado
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


def existe_tipo_antecedente_activo(conn: Connection, id_tipo_antecedente: int) -> bool:
    return (
        _one(
            conn,
            """
            SELECT 1 AS existe
            FROM Catalogo.TipoAntecedente
            WHERE IdTipoAntecedente = :id_tipo_antecedente AND Estado = 'Activo'
            """,
            {"id_tipo_antecedente": id_tipo_antecedente},
        )
        is not None
    )


def listar_evaluaciones_riesgo(
    conn: Connection,
    id_cliente: int,
    *,
    id_evaluacion: int | None = None,
    solo_vigente: bool = False,
) -> list[dict[str, Any]]:
    """Lee los valores finales después del trigger; también permite leer el alta."""
    return _rows(
        conn,
        """
        SELECT r.IdEvaluacion AS id_evaluacion,
               r.IdCliente AS id_cliente,
               r.NivelRiesgoLAFT AS nivel_riesgo_laft,
               r.EsPEP AS es_pep,
               r.ResultadoEvaluacion AS resultado_evaluacion,
               r.FechaEvaluacion AS fecha_evaluacion,
               r.Evaluador AS evaluador,
               r.TieneAntecedentes AS tiene_antecedentes,
               r.IdTipoAntecedente AS id_tipo_antecedente,
               r.Observaciones AS observaciones,
               r.EsVigente AS es_vigente,
               c.Estado AS estado_cliente
        FROM Clientes.RiesgoCliente AS r
        JOIN Clientes.Cliente AS c ON c.IdCliente = r.IdCliente
        WHERE r.IdCliente = :id_cliente
          AND (:id_evaluacion IS NULL OR r.IdEvaluacion = :id_evaluacion)
          AND (:solo_vigente = 0 OR r.EsVigente = 1)
        ORDER BY r.FechaEvaluacion DESC, r.IdEvaluacion DESC
        """,
        {
            "id_cliente": id_cliente,
            "id_evaluacion": id_evaluacion,
            "solo_vigente": solo_vigente,
        },
    )


def insertar_evaluacion_riesgo(
    conn: Connection,
    id_cliente: int,
    datos: dict[str, Any],
    *,
    evaluador: int,
    direccion_ip: str,
) -> dict[str, Any]:
    """Inserta con EsVigente=0; el trigger mantiene vigencia y estado del cliente.

    OUTPUT INTO captura solo la identidad; la lectura posterior refleja los
    cambios del trigger, que OUTPUT INSERTED no devuelve directamente.
    """
    params = {
        **datos,
        "id_cliente": id_cliente,
        "evaluador": evaluador,
        "fecha_evaluacion": datetime.now(UTC),
    }
    row = _one(
        conn,
        """
        SET NOCOUNT ON;
        DECLARE @Evaluacion TABLE (IdEvaluacion INT);
        INSERT INTO Clientes.RiesgoCliente (
            IdCliente, NivelRiesgoLAFT, EsPEP, ResultadoEvaluacion,
            FechaEvaluacion, Evaluador, TieneAntecedentes, IdTipoAntecedente,
            Observaciones, EsVigente
        )
        OUTPUT INSERTED.IdEvaluacion INTO @Evaluacion
        VALUES (
            :id_cliente, :nivel_riesgo_laft, :es_pep, :resultado_evaluacion,
            :fecha_evaluacion, :evaluador, :tiene_antecedentes, :id_tipo_antecedente,
            :observaciones, 0
        );
        SELECT IdEvaluacion AS id_evaluacion FROM @Evaluacion;
        """,
        params,
    )
    if row is None:
        raise RuntimeError("No se pudo obtener la evaluación insertada.")

    filas = listar_evaluaciones_riesgo(
        conn, id_cliente, id_evaluacion=row["id_evaluacion"]
    )
    if not filas:
        raise RuntimeError("No se pudo leer la evaluación después del trigger.")

    _insertar_historial(
        conn,
        id_cliente=id_cliente,
        tipo_operacion="I",
        campo="RIESGO",
        valor_anterior=None,
        modificado_por=evaluador,
        direccion_ip=direccion_ip,
        observaciones=f"Evaluación de riesgo {row['id_evaluacion']} registrada",
    )
    return filas[0]
