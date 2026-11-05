from typing import Any

from sqlalchemy import Connection, text


def _rows(
    conn: Connection, sql: str, params: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(text(sql), params or {}).mappings()]


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


def listar_actividades_economicas(conn: Connection) -> list[dict[str, Any]]:
    # CAT-03: solo activas; el frontend agrupa por área
    return _rows(
        conn,
        """
        SELECT IdActividadEconomica AS id_actividad_economica,
               Descripcion AS descripcion, AreaActividad AS area_actividad
        FROM Catalogo.ActividadEconomica
        WHERE Estado = 'A'
        ORDER BY AreaActividad, Descripcion
        """,
    )


def listar_tipos_antecedente(conn: Connection) -> list[dict[str, Any]]:
    # CAT-04: puede_impedir_vinculacion solo informa; la regla que bloquea vive en C-08
    return _rows(
        conn,
        """
        SELECT IdTipoAntecedente AS id_tipo_antecedente, Nombre AS nombre,
               Categoria AS categoria,
               PuedeImpedirVinculacion AS puede_impedir_vinculacion
        FROM Catalogo.TipoAntecedente
        WHERE Estado = 'Activo'
        ORDER BY Categoria, Nombre
        """,
    )


def listar_productos(conn: Connection, tipo: str | None) -> list[dict[str, Any]]:
    # CAT-07: solo activos; los campos que no aplican al tipo van en NULL
    return _rows(
        conn,
        """
        SELECT IdProducto AS id_producto, CodigoProducto AS codigo_producto,
               NombreProducto AS nombre_producto, TipoProducto AS tipo_producto,
               CASE WHEN TipoProducto = 'Cuenta'
                    THEN MontoAperturaMinimo END AS monto_apertura_minimo,
               CASE WHEN TipoProducto = 'Credito'
                    THEN IdTipoCredito END AS id_tipo_credito,
               CASE WHEN TipoProducto = 'Tarjeta' THEN IdRed END AS id_red,
               CASE WHEN TipoProducto = 'Cuenta' THEN TipoCuenta END AS tipo_cuenta,
               PermiteOperacionesPresenciales AS permite_operaciones_presenciales
        FROM ProductosFinancieros.Producto
        WHERE Estado = 'A' AND (:tipo IS NULL OR TipoProducto = :tipo)
        ORDER BY TipoProducto, NombreProducto
        """,
        {"tipo": tipo},
    )


def listar_canales(conn: Connection) -> list[dict[str, Any]]:
    # CAT-08: solo canales activos, ordenados por nombre.
    return _rows(
        conn,
        """
        SELECT
            IdCanal AS id_canal,
            CodigoCanal AS codigo_canal,
            NombreCanal AS nombre_canal,
            RequiereTarjeta AS requiere_tarjeta,
            RequierePin AS requiere_pin,
            RequiereTerminal AS requiere_terminal,
            RequiereJornadaCaja AS requiere_jornada_caja,
            ModoDigitalPresencial AS modo
        FROM Canal.Canal
        WHERE Estado = 'A'
        ORDER BY NombreCanal ASC""",
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


def listar_tipos_credito(conn: Connection) -> list[dict[str, Any]]:
    # CAT-09: solo tipos activos, ordenados por nombre. Las condiciones
    # (tasa, plazo, montos) se piden con CRE-01.
    return _rows(
        conn,
        """
        SELECT IdTipoCredito AS id_tipo_credito,
               CodigoTipoCredito AS codigo_tipo_credito,
               Nombre AS nombre,
               Descripcion AS descripcion
        FROM Credito.TipoCredito
        WHERE Estado = 'A'
        ORDER BY Nombre
        """,
    )


def _escapar_like(valor: str) -> str:
    # '!' es el carácter de escape; evita que %, _ y [ actúen como comodines.
    for caracter in ("!", "%", "_", "["):
        valor = valor.replace(caracter, "!" + caracter)
    return valor


def existe_pais(conn: Connection, codigo_pais: str) -> bool:
    return bool(
        _rows(
            conn,
            "SELECT 1 AS existe FROM Catalogo.Paises WHERE CodigoPais = :codigo",
            {"codigo": codigo_pais},
        )
    )


def listar_ciudades(
    conn: Connection, codigo_pais: str, q: str | None = None
) -> list[dict[str, Any]]:
    sql = """
        SELECT IdCiudad AS id_ciudad, CodigoPais AS codigo_pais,
               Nombre AS nombre, Provincia AS provincia
        FROM Catalogo.Ciudad
        WHERE CodigoPais = :codigo
    """
    params: dict[str, Any] = {"codigo": codigo_pais}
    if q:
        # Sin mayúsculas ni tildes: la colación de la tabla distingue tildes.
        sql += " AND Nombre COLLATE Latin1_General_CI_AI LIKE :patron ESCAPE '!'"
        params["patron"] = f"%{_escapar_like(q)}%"
    sql += " ORDER BY Provincia, Nombre"
    return _rows(conn, sql, params)
