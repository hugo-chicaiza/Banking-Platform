from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, text

from app.core.database.procedimientos import ejecutar_con_salidas


def _one(
    conn: Connection, sql: str, params: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    fila = conn.execute(text(sql), params or {}).mappings().first()
    return dict(fila) if fila else None


def obtener_por_fecha(conn: Connection, fecha: date) -> dict[str, Any] | None:
    """Fila del calendario contable de un día calendario, o None si no está cargado."""
    return _one(
        conn,
        """
        SELECT IdFechaContable AS id_fecha_contable,
               Fecha           AS fecha,
               EsDiaContable   AS es_dia_contable,
               EsFeriado       AS es_feriado,
               EsFinDeSemana   AS es_fin_de_semana,
               HoraCorte       AS hora_corte
        FROM Contabilidad.FechaContable
        WHERE Fecha = :fecha
        """,
        {"fecha": fecha},
    )


def obtener_por_id(conn: Connection, id_fecha_contable: int) -> dict[str, Any] | None:
    """Fila del calendario contable por su IdFechaContable, o None si no existe."""
    return _one(
        conn,
        """
        SELECT IdFechaContable AS id_fecha_contable,
               Fecha           AS fecha,
               EsDiaContable   AS es_dia_contable,
               EsFeriado       AS es_feriado,
               EsFinDeSemana   AS es_fin_de_semana,
               HoraCorte       AS hora_corte
        FROM Contabilidad.FechaContable
        WHERE IdFechaContable = :id_fecha_contable
        """,
        {"id_fecha_contable": id_fecha_contable},
    )


def id_fecha_contable(conn: Connection, fecha_hora: datetime) -> int | None:
    """IdFechaContable de una operación, según Contabilidad.fn_IdFechaContable.

    La regla (corte 19:00, fines de semana, feriados) vive en la función de la DB
    y NO se reimplementa aquí. Devuelve None si el calendario no cubre la fecha.
    """
    fila = _one(
        conn,
        """
        SELECT Contabilidad.fn_IdFechaContable(CAST(:fecha_hora AS datetime2))
               AS id_fecha_contable
        """,
        {"fecha_hora": fecha_hora},
    )
    return fila["id_fecha_contable"] if fila else None


def listar_cuentas_contables(
    conn: Connection, q: str | None, imputable: bool | None
) -> list[dict[str, Any]]:
    """Plan de cuentas (CON-03) ordenado por código; filtros opcionales.

    `q` busca por código o nombre (sin distinguir mayúsculas; % y _ se toman
    literales). TipoCuenta es una columna calculada de CuentasContables a partir
    de Contabilidad.ElementoCUC, por eso no hace falta el JOIN.
    """
    sql = """
        SELECT IdCuentaContable AS id_cuenta_contable,
               CodigoCuenta     AS codigo_cuenta,
               NombreCuenta     AS nombre_cuenta,
               Naturaleza       AS naturaleza,
               TipoCuenta       AS tipo_cuenta,
               IdCuentaSuperior AS id_cuenta_superior,
               EsImputable      AS es_imputable,
               Saldo            AS saldo,
               Estado           AS estado
        FROM Contabilidad.CuentasContables
        WHERE 1 = 1
    """
    params: dict[str, Any] = {}
    if q is not None:
        sql += """
          AND (CodigoCuenta LIKE :patron ESCAPE '\\'
               OR NombreCuenta LIKE :patron ESCAPE '\\')
        """
        escapado = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        params["patron"] = f"%{escapado}%"
    if imputable is not None:
        sql += " AND EsImputable = :imputable"
        params["imputable"] = 1 if imputable else 0
    sql += " ORDER BY CodigoCuenta"
    return [dict(f) for f in conn.execute(text(sql), params).mappings().all()]


# #206 · Alta y cambio de estado de cuentas contables
# CodigoElemento y TipoCuenta son columnas calculadas de LEFT(CodigoCuenta, 1): la
# hija los hereda del padre porque su código empieza con el del padre. No se insertan.

_CUENTA = """
    SELECT IdCuentaContable  AS id_cuenta_contable,
           CodigoCuenta      AS codigo_cuenta,
           NombreCuenta      AS nombre_cuenta,
           Naturaleza        AS naturaleza,
           TipoCuenta        AS tipo_cuenta,
           IdCuentaSuperior  AS id_cuenta_superior,
           EsImputable       AS es_imputable,
           Saldo             AS saldo,
           Estado            AS estado,
           EsCuentaValuacion AS es_cuenta_valuacion
    FROM Contabilidad.CuentasContables
"""


def obtener_cuenta(conn: Connection, id_cuenta: int) -> dict[str, Any] | None:
    """Una cuenta por id, o None. Sin bloqueo: para leer después de escribir."""
    return _one(conn, _CUENTA + " WHERE IdCuentaContable = :id", {"id": id_cuenta})


def bloquear_cuenta(conn: Connection, id_cuenta: int) -> dict[str, Any] | None:
    """Una cuenta por id, bloqueada hasta el fin de la transacción (UPDLOCK,
    HOLDLOCK): nadie cambia su saldo, estado o hijas mientras se valida."""
    return _one(
        conn,
        _CUENTA + " WITH (UPDLOCK, HOLDLOCK) WHERE IdCuentaContable = :id",
        {"id": id_cuenta},
    )


def existe_codigo(conn: Connection, codigo: str) -> bool:
    """Si ya hay una cuenta con ese código. HOLDLOCK bloquea el rango del índice
    único hasta el commit, así otra transacción no inserta el mismo código entre
    esta lectura y el INSERT (si igual choca, el índice único responde 2601/2627)."""
    fila = _one(
        conn,
        """
        SELECT 1 AS existe
        FROM Contabilidad.CuentasContables WITH (UPDLOCK, HOLDLOCK)
        WHERE CodigoCuenta = :codigo
        """,
        {"codigo": codigo},
    )
    return fila is not None


def tiene_movimientos(conn: Connection, id_cuenta: int) -> bool:
    """Si la cuenta tiene filas en MovimientosContables. HOLDLOCK bloquea el rango
    de IX_MovimientosContables_Cuenta hasta el commit: nadie registra un movimiento
    en la cuenta entre esta lectura y el cambio de EsImputable."""
    fila = _one(
        conn,
        """
        SELECT TOP (1) 1 AS existe
        FROM Contabilidad.MovimientosContables WITH (HOLDLOCK)
        WHERE IdCuentaContable = :id
        """,
        {"id": id_cuenta},
    )
    return fila is not None


def desmarcar_imputable(conn: Connection, id_cuenta: int) -> int:
    """Pone EsImputable = 0 y FechaModificacion (hora de Ecuador); filas afectadas."""
    resultado = conn.execute(
        text(
            """
            UPDATE Contabilidad.CuentasContables
            SET EsImputable = 0,
                FechaModificacion = CONVERT(
                    datetime2,
                    SYSDATETIMEOFFSET() AT TIME ZONE 'SA Pacific Standard Time'
                )
            WHERE IdCuentaContable = :id AND EsImputable = 1
            """
        ),
        {"id": id_cuenta},
    )
    return resultado.rowcount


def insertar_cuenta(conn: Connection, datos: dict[str, Any]) -> int:
    """Inserta la cuenta con Estado = 1 y Saldo = 0; devuelve su IdCuentaContable.

    `datos`: codigo, nombre, naturaleza, id_superior, imputable, valuacion.
    La tabla tiene el trigger trg_CuentasContables_PadreNoImputable: SQL Server no
    admite OUTPUT sin INTO sobre una tabla con triggers (error 334), por eso el id
    pasa por una variable de tabla.
    """
    return int(
        conn.execute(
            text(
                """
                SET NOCOUNT ON;
                DECLARE @ids TABLE (IdCuentaContable int);
                INSERT INTO Contabilidad.CuentasContables
                    (CodigoCuenta, NombreCuenta, Naturaleza, IdCuentaSuperior,
                     Saldo, Estado, EsImputable, EsCuentaValuacion)
                OUTPUT INSERTED.IdCuentaContable INTO @ids
                VALUES (:codigo, :nombre, :naturaleza, :id_superior,
                        0, 1, :imputable, :valuacion);
                SELECT IdCuentaContable FROM @ids;
                """
            ),
            datos,
        ).scalar_one()
    )


def actualizar_estado_cuenta(conn: Connection, id_cuenta: int, activa: bool) -> int:
    """Cambia el bit Estado y FechaModificacion (hora de Ecuador); filas afectadas."""
    resultado = conn.execute(
        text(
            """
            UPDATE Contabilidad.CuentasContables
            SET Estado = :estado,
                FechaModificacion = CONVERT(
                    datetime2,
                    SYSDATETIMEOFFSET() AT TIME ZONE 'SA Pacific Standard Time'
                )
            WHERE IdCuentaContable = :id
            """
        ),
        {"id": id_cuenta, "estado": 1 if activa else 0},
    )
    return resultado.rowcount


# CON-04 / CON-05 · Asientos contables

# Lista blanca del sort de CON-04: campo del contrato -> columna. Solo estos nombres
# de columna y los literales ASC/DESC llegan al ORDER BY; nunca texto del cliente.
ORDEN_ASIENTOS = {
    "fechaAsiento": "FechaAsiento",
    "numeroAsiento": "NumeroAsiento",
    "idAsientoContable": "IdAsientoContable",
    "totalDebito": "TotalDebito",
    "estado": "Estado",
    "origen": "Origen",
}

_ASIENTO = """
    SELECT IdAsientoContable  AS id_asiento_contable,
           NumeroAsiento      AS numero_asiento,
           FechaAsiento       AS fecha_asiento,
           IdTipoAsiento      AS id_tipo_asiento,
           Origen             AS origen,
           Concepto           AS concepto,
           TotalDebito        AS total_debito,
           TotalCredito       AS total_credito,
           Estado             AS estado,
           IdAsientoReversion AS id_asiento_reversion,
           IdAgencia          AS id_agencia
    FROM Contabilidad.AsientoContable
"""

# Filtros de CON-04: parámetro -> condición (todas por igualdad).
_FILTROS_ASIENTOS = {
    "fecha": "FechaAsiento = :fecha",
    "origen": "Origen = :origen",
    "id_agencia": "IdAgencia = :id_agencia",
    "estado": "Estado = :estado",
}


def listar_asientos(
    conn: Connection,
    filtros: dict[str, Any],
    page: int,
    page_size: int,
    campo: str,
    direccion: str,
) -> tuple[list[dict[str, Any]], int]:
    """Página de asientos (CON-04) y el total que cumple los filtros.

    `filtros` trae fecha, origen, id_agencia y estado (None = sin filtro). `campo`
    debe estar en ORDEN_ASIENTOS; el desempate es IdAsientoContable DESC.
    """
    params = {k: v for k, v in filtros.items() if v is not None}
    where = "".join(f" AND {_FILTROS_ASIENTOS[k]}" for k in params)
    where = " WHERE 1 = 1" + where
    # SQL dinámico seguro: `where` solo se arma con fragmentos fijos de
    # _FILTROS_ASIENTOS (las claves vienen del servicio, no del cliente) y los
    # valores de los filtros van como parámetros enlazados, nunca en el texto.
    sql_total = "SELECT COUNT(*) FROM Contabilidad.AsientoContable" + where  # nosec B608  # NOSONAR
    total = int(conn.execute(text(sql_total), params).scalar_one())
    columna = ORDEN_ASIENTOS[campo]
    orden = "ASC" if direccion == "asc" else "DESC"
    desempate = "" if campo == "idAsientoContable" else ", IdAsientoContable DESC"
    # Igual que arriba: `where` solo tiene fragmentos fijos de _FILTROS_ASIENTOS y
    # los valores van parametrizados. El ORDER BY usa columnas de ORDEN_ASIENTOS y
    # los literales ASC/DESC; offset y page_size también son parámetros.
    sql = (
        _ASIENTO
        + where  # nosec B608  # NOSONAR
        + f" ORDER BY {columna} {orden}{desempate}"
        + " OFFSET :offset ROWS FETCH NEXT :page_size ROWS ONLY"
    )
    filas = conn.execute(
        text(sql),
        {**params, "offset": (page - 1) * page_size, "page_size": page_size},
    ).mappings()
    return [dict(f) for f in filas.all()], total


def obtener_asiento(conn: Connection, id_asiento: int) -> dict[str, Any] | None:
    """Cabecera de un asiento (CON-05), o None si no existe."""
    return _one(conn, _ASIENTO + " WHERE IdAsientoContable = :id", {"id": id_asiento})


def movimientos_asiento(conn: Connection, id_asiento: int) -> list[dict[str, Any]]:
    """Líneas de un asiento (CON-05) con el código de la cuenta, en orden de registro."""
    sql = """
        SELECT m.IdMovimientoContable AS id_movimiento_contable,
               m.IdCuentaContable     AS id_cuenta_contable,
               c.CodigoCuenta         AS codigo_cuenta,
               m.TipoMovimiento       AS tipo_movimiento,
               m.Monto                AS monto,
               m.IdTransaccion        AS id_transaccion,
               m.IdAgencia            AS id_agencia
        FROM Contabilidad.MovimientosContables m
        JOIN Contabilidad.CuentasContables c
          ON c.IdCuentaContable = m.IdCuentaContable
        WHERE m.IdAsientoContable = :id
        ORDER BY m.IdMovimientoContable
    """
    filas = conn.execute(text(sql), {"id": id_asiento}).mappings().all()
    return [dict(f) for f in filas]


def plantilla_boveda(
    conn: Connection, agencia: str, tipo: str, naturaleza: str
) -> dict[str, Any] | None:
    return _one(
        conn,
        """
        SELECT p.IdCuentaDebito AS debito, p.IdCuentaCredito AS credito,
               p.IdTipoAsiento AS tipo_asiento, t.Estado AS estado_tipo
        FROM Contabilidad.PlantillaBoveda p WITH (HOLDLOCK)
        JOIN Contabilidad.TiposAsiento t WITH (HOLDLOCK) ON t.IdTipoAsiento = p.IdTipoAsiento
        WHERE p.IdAgencia = :agencia AND p.TipoMovimiento = :tipo AND p.Naturaleza = :naturaleza
    """,
        {"agencia": agencia, "tipo": tipo, "naturaleza": naturaleza},
    )


def periodo_boveda(conn: Connection, id_fecha: int) -> dict[str, Any] | None:
    return _one(
        conn,
        """
        SELECT f.Fecha AS fecha, p.Estado AS estado
        FROM Contabilidad.FechaContable f
        LEFT JOIN Contabilidad.PeriodoContable p WITH (UPDLOCK, HOLDLOCK)
               ON p.Anio = f.Anio AND p.Mes = f.Mes
        WHERE f.IdFechaContable = :id
    """,
        {"id": id_fecha},
    )


def cuenta_boveda(conn: Connection, id_cuenta: int) -> dict[str, Any] | None:
    return _one(
        conn,
        """
        SELECT Estado AS estado, EsImputable AS imputable, Naturaleza AS naturaleza
        FROM Contabilidad.CuentasContables WITH (UPDLOCK, HOLDLOCK)
        WHERE IdCuentaContable = :id
    """,
        {"id": id_cuenta},
    )


def crear_asiento_boveda(conn: Connection, datos: dict[str, Any]) -> int:
    numero = ejecutar_con_salidas(
        conn,
        """
        DECLARE @Numero varchar(20);
        EXEC Contabilidad.usp_GenerarNumeroAsiento @FechaAsiento = ?, @IdAgencia = ?, @NumeroAsiento = @Numero OUTPUT;
        SELECT @Numero AS numero;
    """,
        (datos["fecha"], datos["agencia"]),
    )["numero"]
    return int(
        conn.execute(
            text("""
        INSERT INTO Contabilidad.AsientoContable
            (NumeroAsiento, FechaAsiento, FechaSistema, IdTipoAsiento, Origen,
             Concepto, TotalDebito, TotalCredito, Estado, IdUsuarioCreacion, IdAgencia, IdFechaContable)
        OUTPUT INSERTED.IdAsientoContable
        VALUES (:numero, :fecha, :ahora, :tipo_asiento, 'BOVEDA', :concepto,
                0, 0, 'BORRADOR', :actor, :agencia, :fecha_contable)
    """),
            {**datos, "numero": numero},
        ).scalar_one()
    )


def linea_boveda(
    conn: Connection,
    asiento: int,
    cuenta: int,
    agencia: str,
    monto: Decimal,
    tipo: str,
    ahora: datetime,
    naturaleza: str,
) -> None:
    conn.execute(
        text("""
        INSERT INTO Contabilidad.MovimientosContables
            (IdCuentaContable, IdAgencia, TipoMovimiento, Monto, FechaHora, IdAsientoContable)
        VALUES (:cuenta, :agencia, :tipo, :monto, :ahora, :asiento)
    """),
        {
            "cuenta": cuenta,
            "agencia": agencia,
            "tipo": tipo,
            "monto": monto,
            "ahora": ahora,
            "asiento": asiento,
        },
    )
    delta = monto if (tipo == "DEBITO") == (naturaleza == "DEUDORA") else -monto
    conn.execute(
        text("""
        UPDATE Contabilidad.CuentasContables SET Saldo = Saldo + :delta, FechaModificacion = :ahora
        WHERE IdCuentaContable = :cuenta
    """),
        {"cuenta": cuenta, "delta": delta, "ahora": ahora},
    )


def confirmar_asiento_boveda(conn: Connection, id_asiento: int) -> None:
    conn.execute(
        text("EXEC Contabilidad.usp_ContabilizarAsiento @IdAsientoContable = :id"),
        {"id": id_asiento},
    )


def buscar_asiento_evento(conn: Connection, clave: str) -> dict[str, Any] | None:
    return _one(
        conn,
        """
        SELECT IdAsientoContable, HuellaEventoContable, Estado
        FROM Contabilidad.AsientoContable WITH (UPDLOCK, HOLDLOCK)
        WHERE ClaveEventoContable = :clave
        """,
        {"clave": clave},
    )


def obtener_plantilla(
    conn: Connection, codigo: str, fecha: date
) -> dict[str, Any] | None:
    return _one(
        conn,
        """
        SELECT TOP (1) p.IdPlantillaAsiento, p.IdConceptoContable, p.Origen, p.IdTipoAsiento,
               p.Nombre, p.Estado
        FROM Contabilidad.PlantillaAsiento p WITH (HOLDLOCK)
        JOIN Contabilidad.TiposAsiento t WITH (HOLDLOCK) ON t.IdTipoAsiento=p.IdTipoAsiento
        WHERE p.CodigoPlantilla = :codigo AND p.Estado = 1 AND t.Estado = 'A' AND t.EsManual = 0
          AND VigenciaDesde <= :fecha AND (VigenciaHasta IS NULL OR VigenciaHasta >= :fecha)
        ORDER BY VigenciaDesde DESC, Version DESC
        """,
        {"codigo": codigo, "fecha": fecha},
    )


def obtener_lineas_plantilla(
    conn: Connection, id_plantilla: int
) -> list[dict[str, Any]]:
    filas = conn.execute(
        text(
            """
            SELECT d.IdCuentaContable, d.TipoMovimiento, d.ComponenteImporte, d.OrigenCuenta, d.CodigoRol,
                   c.Estado, c.EsImputable, c.CodigoCuenta
            FROM Contabilidad.PlantillaAsientoDetalle AS d WITH (HOLDLOCK)
            LEFT JOIN Contabilidad.CuentasContables AS c
                ON c.IdCuentaContable = d.IdCuentaContable
            WHERE d.IdPlantillaAsiento = :id
            ORDER BY d.Orden
            """
        ),
        {"id": id_plantilla},
    ).mappings()
    return [dict(fila) for fila in filas]


def periodo_abierto(conn: Connection, fecha: date) -> bool:
    fila = _one(
        conn,
        """
        SELECT Estado
        FROM Contabilidad.PeriodoContable WITH (HOLDLOCK)
        WHERE Anio = :anio AND Mes = :mes
        """,
        {"anio": fecha.year, "mes": fecha.month},
    )
    return fila is not None and fila["Estado"] == "ABIERTO"


def insertar_asiento_automatico(conn: Connection, datos: dict[str, Any]) -> int:
    valor = conn.execute(
        text(
            """
            SET NOCOUNT ON;
            DECLARE @numero varchar(20);
            DECLARE @asiento TABLE (IdAsientoContable int NOT NULL);

            EXEC Contabilidad.usp_GenerarNumeroAsiento
                @FechaAsiento = :fecha, @IdAgencia = :agencia,
                @NumeroAsiento = @numero OUTPUT;

            INSERT INTO Contabilidad.AsientoContable (
                NumeroAsiento, FechaAsiento, FechaSistema, IdTipoAsiento, Origen,
                Concepto, TotalDebito, TotalCredito, Estado, IdUsuarioCreacion,
                IdAgencia, IdConceptoContable, IdFechaContable, IdPlantillaAsiento,
                ClaveEventoContable, HuellaEventoContable, IdTransaccion, IdAsientoReversion
            )
            OUTPUT inserted.IdAsientoContable INTO @asiento
            VALUES (
                @numero, :fecha, :fecha_hora, :tipo, :origen, :nombre, 0, 0,
                'BORRADOR', :usuario, :agencia, :concepto, :id_fecha,
                :plantilla, :evento, :huella, :transaccion, :original
            );

            SELECT IdAsientoContable FROM @asiento;
            """
        ),
        datos,
    ).scalar_one()
    return int(valor)


def insertar_lineas_asiento(conn: Connection, lineas: list[dict[str, Any]]) -> None:
    conn.execute(
        text(
            """
            INSERT INTO Contabilidad.MovimientosContables (
                IdCuentaContable, IdTransaccion, IdAgencia, TipoMovimiento,
                Monto, FechaHora, IdAsientoContable
            )
            VALUES (:cuenta, :transaccion, :agencia, :lado, :monto, :fecha_hora, :asiento)
            """
        ),
        lineas,
    )


def contabilizar_asiento(conn: Connection, id_asiento: int) -> None:
    confirmar_asiento_boveda(conn, id_asiento)
    conn.execute(
        text("EXEC Contabilidad.usp_E401_AplicarSaldos @IdAsiento = :id"),
        {"id": id_asiento},
    )


def cuenta_para_plantilla(conn: Connection, id_cuenta: int) -> dict[str, Any] | None:
    return _one(
        conn,
        """
        SELECT Estado, EsImputable, CodigoCuenta
        FROM Contabilidad.CuentasContables WITH (HOLDLOCK)
        WHERE IdCuentaContable=:id
        """,
        {"id": id_cuenta},
    )
