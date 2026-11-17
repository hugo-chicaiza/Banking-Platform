from datetime import date
from typing import Any

from sqlalchemy import Connection, text

from app.modules.catalogos.subproductos import tipo_tarjeta_de


def _rows(
    conn: Connection, sql: str, params: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(text(sql), params or {}).mappings()]


def listar_paises(conn: Connection) -> list[dict[str, Any]]:
    # CAT-01: solo activos (Estado desde la migración 20261116)
    return _rows(
        conn,
        """
        SELECT CodigoPais AS codigo_pais, CodigoNumerico AS codigo_numerico,
               NombrePais AS nombre_pais
        FROM Catalogo.Paises
        WHERE Estado = 'A'
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
    # CAT-10: solo activos (Estado desde la migración 20261116)
    return _rows(
        conn,
        """
        SELECT IdTipoMovimientoCaja AS id_tipo_movimiento_caja, Codigo AS codigo,
               Descripcion AS descripcion, Naturaleza AS naturaleza
        FROM Caja.TipoMovimientoCaja
        WHERE Estado = 'A'
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


# Edad mínima que rige para un subproducto `s` de un producto `p` (la más alta de):
#   - la del subproducto (SubProducto.EdadMinima);
#   - en tarjetas, la de su red (Red.EdadMinima);
#   - en créditos, la política EDAD_MINIMA vigente (Credito.ParametroPolitica, la misma
#     regla que aplica usp_EvaluarSolicitudCredito al evaluar).
# La edad máxima es solo la del subproducto. El bloque (LEFT JOIN r, OUTER APPLY pol,
# CROSS APPLY e con e.EdadMinima) va repetido literal en cada consulta: el SQL no se arma con texto.


def reglas_edad(conn: Connection, id_sub: int) -> dict[str, Any]:
    """Las tres fuentes de la edad mínima de un subproducto y la que rige."""
    filas = _rows(
        conn,
        """
        SELECT s.EdadMinima AS subproducto, r.EdadMinima AS red,
               pol.Valor AS politica, e.EdadMinima AS efectiva,
               s.EdadMaxima AS maxima
        FROM ProductosFinancieros.SubProducto AS s
        JOIN ProductosFinancieros.Producto AS p ON p.IdProducto = s.IdProducto
        LEFT JOIN ProductosFinancieros.Red AS r
               ON r.IdRed = p.IdRed AND p.TipoProducto = 'Tarjeta'
        OUTER APPLY (
            SELECT TOP 1 CAST(pp.Valor AS int) AS Valor
            FROM Credito.ParametroPolitica AS pp
            WHERE p.TipoProducto = 'Credito' AND pp.Clave = 'EDAD_MINIMA'
              AND pp.Estado = 'Activo'
              AND pp.VigenciaDesde <= CAST(SYSDATETIMEOFFSET() AT TIME ZONE
                    'SA Pacific Standard Time' AS date)
              AND (pp.VigenciaHasta IS NULL OR pp.VigenciaHasta > CAST(SYSDATETIMEOFFSET()
                    AT TIME ZONE 'SA Pacific Standard Time' AS date))
            ORDER BY pp.VigenciaDesde DESC
        ) AS pol
        CROSS APPLY (
            SELECT MAX(v) AS EdadMinima
            FROM (VALUES (CAST(s.EdadMinima AS int)), (CAST(r.EdadMinima AS int)),
                         (pol.Valor)) AS x (v)
        ) AS e
        WHERE s.IdSubProducto = :id
        """,
        {"id": id_sub},
    )
    return filas[0] if filas else {}


def listar_productos(
    conn: Connection,
    tipo: str | None,
    tipo_tarjeta: str | None = None,
    edad: int | None = None,
) -> list[dict[str, Any]]:
    # CAT-07: solo activos; los campos que no aplican al tipo van en NULL. Cada
    # producto lleva sus subproductos activos (lo que el asesor puede ofrecer).
    # tipo_tarjeta deja solo productos Tarjeta y sus subproductos de ese tipo
    if tipo_tarjeta is not None:
        tipo = "Tarjeta"
    productos = _rows(
        conn,
        """
        SELECT IdProducto AS id_producto, CodigoProducto AS codigo_producto,
               NombreProducto AS nombre_producto, Descripcion AS descripcion,
               TipoProducto AS tipo_producto,
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
    subproductos = _rows(
        conn,
        """
        SELECT s.IdProducto AS id_producto, s.IdSubProducto AS id_sub_producto,
               s.CodigoSubProducto AS codigo_sub_producto,
               s.NombreSubProducto AS nombre_sub_producto,
               p.TipoProducto AS tipo_producto
        FROM ProductosFinancieros.SubProducto AS s
        JOIN ProductosFinancieros.Producto AS p ON p.IdProducto = s.IdProducto
        LEFT JOIN ProductosFinancieros.Red AS r
               ON r.IdRed = p.IdRed AND p.TipoProducto = 'Tarjeta'
        OUTER APPLY (
            SELECT TOP 1 CAST(pp.Valor AS int) AS Valor
            FROM Credito.ParametroPolitica AS pp
            WHERE p.TipoProducto = 'Credito' AND pp.Clave = 'EDAD_MINIMA'
              AND pp.Estado = 'Activo'
              AND pp.VigenciaDesde <= CAST(SYSDATETIMEOFFSET() AT TIME ZONE
                    'SA Pacific Standard Time' AS date)
              AND (pp.VigenciaHasta IS NULL OR pp.VigenciaHasta > CAST(SYSDATETIMEOFFSET()
                    AT TIME ZONE 'SA Pacific Standard Time' AS date))
            ORDER BY pp.VigenciaDesde DESC
        ) AS pol
        CROSS APPLY (
            SELECT MAX(v) AS EdadMinima
            FROM (VALUES (CAST(s.EdadMinima AS int)), (CAST(r.EdadMinima AS int)),
                         (pol.Valor)) AS x (v)
        ) AS e
        WHERE s.Estado = 'A' AND p.Estado = 'A'
          AND (:tipo IS NULL OR p.TipoProducto = :tipo)
          -- Elegibilidad: edad -1 = cliente sin fecha de nacimiento (solo sin límites)
          AND (:edad IS NULL
               OR (:edad >= 0 AND (e.EdadMinima IS NULL OR :edad >= e.EdadMinima)
                   AND (s.EdadMaxima IS NULL OR :edad <= s.EdadMaxima))
               OR (:edad < 0 AND e.EdadMinima IS NULL AND s.EdadMaxima IS NULL))
        ORDER BY s.NombreSubProducto
        """,
        {"tipo": tipo, "edad": edad},
    )
    por_producto: dict[int, list[dict[str, Any]]] = {}
    for sub in subproductos:
        es_tarjeta = sub.pop("tipo_producto") == "Tarjeta"
        sub["tipo_tarjeta"] = (
            tipo_tarjeta_de(sub["codigo_sub_producto"]) if es_tarjeta else None
        )
        if tipo_tarjeta is None or sub["tipo_tarjeta"] == tipo_tarjeta:
            por_producto.setdefault(sub.pop("id_producto"), []).append(sub)
    for producto in productos:
        producto["subproductos"] = por_producto.get(producto["id_producto"], [])
    if tipo_tarjeta is not None or edad is not None:
        # Solo los productos que tienen algo que ofrecer (de ese tipo o a ese cliente)
        productos = [p for p in productos if p["subproductos"]]
    return productos


def listar_sistemas_amortizacion(conn: Connection) -> list[dict[str, Any]]:
    return _rows(
        conn,
        """
        SELECT Codigo AS codigo, Nombre AS nombre, Descripcion AS descripcion
        FROM Catalogo.SistemaAmortizacion
        WHERE Estado = 'A'
        ORDER BY Nombre
        """,
    )


_TASAS = """
    SELECT t.IdTasaInteres AS id_tasa_interes, t.TipoTasa AS tipo_tasa,
           t.IdTipoCredito AS id_tipo_credito,
           tc.Nombre AS nombre_tipo_credito, t.TasaNominalAnual AS tasa_nominal_anual,
           t.RecargoMoraSobreTasa AS recargo_mora_sobre_tasa,
           t.PlazoMaximoMeses AS plazo_maximo_meses, t.MontoMinimo AS monto_minimo,
           t.MontoMaximo AS monto_maximo, t.VigenciaDesde AS vigencia_desde,
           t.VigenciaHasta AS vigencia_hasta,
           CAST(CASE WHEN t.VigenciaDesde <= :hoy
                      AND (t.VigenciaHasta IS NULL OR t.VigenciaHasta >= :hoy)
                THEN 1 ELSE 0 END AS bit) AS vigente
    FROM Credito.TasaInteres AS t
    LEFT JOIN Credito.TipoCredito AS tc ON tc.IdTipoCredito = t.IdTipoCredito
"""


def listar_tasas_interes(
    conn: Connection,
    hoy: date,
    id_tipo_credito: int | None = None,
    tipo_tasa: str | None = None,
) -> list[dict[str, Any]]:
    return _rows(
        conn,
        _TASAS
        + """
        WHERE t.Estado = 'A' AND (:tipo IS NULL OR t.IdTipoCredito = :tipo)
          AND (:tipo_tasa IS NULL OR t.TipoTasa = :tipo_tasa)
        ORDER BY t.TipoTasa, tc.Nombre, t.VigenciaDesde DESC, t.MontoMinimo
        """,
        {"hoy": hoy, "tipo": id_tipo_credito, "tipo_tasa": tipo_tasa},
    )


def obtener_tasa_interes(
    conn: Connection, id_tasa: int, hoy: date
) -> dict[str, Any] | None:
    filas = _rows(
        conn, _TASAS + " WHERE t.IdTasaInteres = :id", {"hoy": hoy, "id": id_tasa}
    )
    return filas[0] if filas else None


def insertar_tasa_interes(conn: Connection, datos: dict[str, Any]) -> int:
    return int(
        conn.execute(
            text(
                """
                INSERT INTO Credito.TasaInteres (
                    TipoTasa, IdTipoCredito, PlazoMaximoMeses, TasaNominalAnual, RecargoMoraSobreTasa,
                    MontoMinimo, MontoMaximo, VigenciaDesde, VigenciaHasta)
                OUTPUT inserted.IdTasaInteres
                VALUES (:tipo_tasa, :id_tipo_credito, :plazo_maximo_meses, :tasa_nominal_anual,
                        :recargo_mora_sobre_tasa, :monto_minimo, :monto_maximo,
                        :vigencia_desde, :vigencia_hasta)
                """
            ),
            datos,
        ).scalar_one()
    )


def existe_tipo_credito_activo(conn: Connection, id_tipo_credito: int) -> bool:
    return bool(
        _rows(
            conn,
            "SELECT 1 AS x FROM Credito.TipoCredito WHERE IdTipoCredito = :id AND Estado = 'A'",
            {"id": id_tipo_credito},
        )
    )


def listar_redes(conn: Connection) -> list[dict[str, Any]]:
    # Redes de tarjeta activas: las que puede elegir un producto Tarjeta
    return _rows(
        conn,
        """
        SELECT IdRed AS id_red, CodigoRed AS codigo_red, Nombre AS nombre
        FROM ProductosFinancieros.Red
        WHERE Estado = 'A'
        ORDER BY Nombre
        """,
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
    # Orden: Matriz primero, luego por código (no depende de cómo se nombre el código).
    return _rows(
        conn,
        """
        SELECT a.IdAgencia AS id_agencia, a.Codigo AS codigo,
               a.Codigo AS nombre, a.TipoAgencia AS tipo_agencia,
               c.Provincia AS provincia, c.Nombre AS ciudad,
               a.Estado AS estado
        FROM Organizacion.Agencia AS a
        JOIN Catalogo.Ciudad AS c ON c.IdCiudad = a.IdCiudad
        ORDER BY CASE a.TipoAgencia WHEN 'Matriz' THEN 0 ELSE 1 END, a.Codigo
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
        WHERE CodigoPais = :codigo AND Estado = 'A'
    """
    params: dict[str, Any] = {"codigo": codigo_pais}
    if q:
        # Sin mayúsculas ni tildes: la colación de la tabla distingue tildes.
        sql += " AND Nombre COLLATE Latin1_General_CI_AI LIKE :patron ESCAPE '!'"
        params["patron"] = f"%{_escapar_like(q)}%"
    sql += " ORDER BY Provincia, Nombre"
    return _rows(conn, sql, params)


def listar_comisiones(conn: Connection) -> list[dict[str, Any]]:
    """Comisiones y recargos activos: los que se pueden vincular a un producto."""
    return _rows(
        conn,
        """
        SELECT c.IdComision AS id_comision, c.CodigoComision AS codigo_comision,
               c.TipoComision AS tipo_comision, c.TipoCalculo AS tipo_calculo,
               c.Valor AS valor, ca.NombreCanal AS nombre_canal, c.Descripcion AS descripcion
        FROM Transacciones.Comisiones AS c
        JOIN Canal.Canal AS ca ON ca.IdCanal = c.IdCanal
        WHERE c.Estado = 'A'
        ORDER BY c.TipoComision, c.CodigoComision
        """,
    )


def listar_seguros(conn: Connection) -> list[dict[str, Any]]:
    return _rows(
        conn,
        """
        SELECT IdSeguro AS id_seguro, CodigoSeguro AS codigo_seguro, Nombre AS nombre,
               Aseguradora AS aseguradora, TipoCalculo AS tipo_calculo, Valor AS valor
        FROM Credito.Seguro
        WHERE Estado = 'A'
        ORDER BY Nombre
        """,
    )


def fecha_nacimiento_cliente(conn: Connection, id_cliente: int) -> tuple[bool, Any]:
    """(existe el cliente, su fecha de nacimiento o None)."""
    fila = conn.execute(
        text("SELECT FechaNacimiento FROM Clientes.Cliente WHERE IdCliente = :id"),
        {"id": id_cliente},
    ).first()
    return (fila is not None, fila[0] if fila else None)
