from datetime import date, timedelta
from typing import Any

from sqlalchemy import Connection, text

from app.core.database.procedimientos import ejecutar_con_salidas

Fila = dict[str, Any]


def _filas(conn: Connection, sql: str, parametros: dict[str, Any]) -> list[Fila]:
    return [dict(fila) for fila in conn.execute(text(sql), parametros).mappings()]


def _fila(conn: Connection, sql: str, parametros: dict[str, Any]) -> Fila | None:
    fila = conn.execute(text(sql), parametros).mappings().first()
    return dict(fila) if fila is not None else None


# --- CAJ-01 cajas físicas ------------------------------------------------------------

_CAJAS = """
SELECT IdCajaFisica, IdAgencia, CodigoCaja, Estado, DescripcionEstado,
       LimiteEfectivoCaja
FROM Caja.CajaFisica
WHERE 1 = 1
"""
_FILTROS_CAJAS = {
    "id_agencia": " AND IdAgencia = :id_agencia",
    "activa": " AND Estado = :activa",
}


def listar_cajas_fisicas(
    conn: Connection, id_agencia: str | None, activa: bool | None
) -> list[Fila]:
    parametros = {
        clave: valor
        for clave, valor in {"id_agencia": id_agencia, "activa": activa}.items()
        if valor is not None
    }
    sql = (
        _CAJAS
        + "".join(_FILTROS_CAJAS[clave] for clave in parametros)
        + " ORDER BY IdAgencia, CodigoCaja"
    )
    return _filas(conn, sql, parametros)


# --- CAJ-02: Consulta de jornadas ------------------------------------

_ORDEN_JORNADAS = {
    "idJornadaCaja": "IdJornadaCaja",
    "idUsuario": "IdUsuario",
    "idCajaFisica": "IdCajaFisica",
    "idAgencia": "IdAgencia",
    "fechaHoraApertura": "FechaHoraApertura",
    "fechaHoraCierre": "FechaHoraCierre",
    "dineroInicial": "DineroInicial",
    "estado": "Estado",
}

_BASE_JORNADAS = """
FROM Caja.JornadasCaja
WHERE 1 = 1
"""

_FILTROS_JORNADAS = {
    "id_agencia": " AND IdAgencia = :id_agencia",
    "id_usuario": " AND IdUsuario = :id_usuario",
    "estado": " AND Estado = :estado",
    "desde": " AND FechaHoraApertura >= :desde",
    "hasta_exclusivo": " AND FechaHoraApertura < :hasta_exclusivo",
}


def listar_jornadas(
    conn: Connection,
    *,
    id_agencia: str | None,
    id_usuario: int | None,
    estado: str | None,
    desde: date | None,
    hasta: date | None,
    page: int,
    page_size: int,
    sort: str,
) -> tuple[list[Fila], int]:
    """Consulta jornadas con filtros, paginación y orden seguro."""

    campo, direccion = sort.split(",", maxsplit=1)

    # Los nombres de columnas nunca provienen directamente del usuario.
    columna = _ORDEN_JORNADAS[campo]
    orden = direccion.upper()

    parametros: dict[str, Any] = {}

    if id_agencia is not None:
        parametros["id_agencia"] = id_agencia

    if id_usuario is not None:
        parametros["id_usuario"] = id_usuario

    if estado is not None:
        parametros["estado"] = estado

    if desde is not None:
        parametros["desde"] = desde

    if hasta is not None:
        # Límite superior exclusivo para incluir todo el día.
        parametros["hasta_exclusivo"] = hasta + timedelta(days=1)

    filtros = "".join(
        fragmento
        for clave, fragmento in _FILTROS_JORNADAS.items()
        if clave in parametros
    )

    where_sql = _BASE_JORNADAS + filtros

    total = conn.execute(
        text("SELECT COUNT_BIG(*) " + where_sql),
        parametros,
    ).scalar_one()

    parametros_pagina = {
        **parametros,
        "offset": (page - 1) * page_size,
        "page_size": page_size,
    }

    # IdJornadaCaja desempata para garantizar paginación estable.
    desempate = "" if campo == "idJornadaCaja" else ", IdJornadaCaja DESC"

    sql = f"""
    SELECT
        IdJornadaCaja,
        IdUsuario,
        IdCajaFisica,
        RTRIM(IdAgencia) AS IdAgencia,
        FechaHoraApertura,
        FechaHoraCierre,
        DineroInicial,
        Estado,
        Observacion
    {where_sql}
    ORDER BY {columna} {orden}{desempate}
    OFFSET :offset ROWS
    FETCH NEXT :page_size ROWS ONLY
    """

    filas = _filas(conn, sql, parametros_pagina)

    return filas, int(total)


# --- CAJ-05: detalle de jornada ---

_COLUMNAS_JORNADA = """
IdJornadaCaja, IdUsuario, IdCajaFisica, IdAgencia, FechaHoraApertura,
FechaHoraCierre, DineroInicial, Estado, Observacion
"""


def obtener_jornada(
    conn: Connection,
    id_jornada: int,
    bloquear: bool = False,
) -> Fila | None:
    consulta_normal = """
        SELECT
            IdJornadaCaja, IdUsuario, IdCajaFisica, IdAgencia,
            FechaHoraApertura, FechaHoraCierre, DineroInicial,
            Estado, Observacion
        FROM Caja.JornadasCaja
        WHERE IdJornadaCaja = :id
    """

    consulta_bloqueada = """
        SELECT
            IdJornadaCaja, IdUsuario, IdCajaFisica, IdAgencia,
            FechaHoraApertura, FechaHoraCierre, DineroInicial,
            Estado, Observacion
        FROM Caja.JornadasCaja WITH (UPDLOCK, HOLDLOCK)
        WHERE IdJornadaCaja = :id
    """

    consulta = consulta_bloqueada if bloquear else consulta_normal
    return _fila(conn, consulta, {"id": id_jornada})


# --- CAJ-08: dotaciones de la jornada ----------


def listar_dotaciones(conn: Connection, id_jornada: int) -> list[Fila]:
    return _filas(
        conn,
        """
        SELECT
            IdDotacionCaja,
            IdJornadaCaja,
            IdBoveda,
            TipoDotacion,
            Monto,
            IdMovimientoBoveda,
            Estado,
            AutorizadoPor
        FROM Caja.DotacionesCaja
        WHERE IdJornadaCaja = :id
        ORDER BY IdDotacionCaja
        """,
        {"id": id_jornada},
    )


# --- CAJ-12: movimientos de caja ----------


_MOVIMIENTOS = """
SELECT mc.IdMovimientoCaja, mc.IdTransaccion, mc.IdJornadaCaja,
       mc.IdTipoMovimiento, tm.Codigo AS CodigoTipoMovimiento,
       tm.Naturaleza, mc.Monto, mc.FechaHora, mc.Observacion,
       mc.IdAsientoContable
FROM Caja.MovimientosCaja mc
JOIN Caja.TipoMovimientoCaja tm
  ON tm.IdTipoMovimientoCaja = mc.IdTipoMovimiento
WHERE mc.IdJornadaCaja = :id
"""


ORDEN_MOVIMIENTOS = {
    "fechaHora": "mc.FechaHora",
    "monto": "mc.Monto",
    "idMovimientoCaja": "mc.IdMovimientoCaja",
}


def listar_movimientos(
    conn: Connection,
    id_jornada: int,
    orden: tuple[str, str],
    offset: int,
    limite: int,
) -> tuple[list[Fila], int]:
    columna = ORDEN_MOVIMIENTOS[orden[0]]
    direccion = "DESC" if orden[1] == "desc" else "ASC"

    total = conn.execute(
        text(
            """
            SELECT COUNT_BIG(*)
            FROM Caja.MovimientosCaja
            WHERE IdJornadaCaja = :id
            """
        ),
        {"id": id_jornada},
    ).scalar_one()

    # Columna y direccion proceden de valores permitidos.
    orden_sql = f" ORDER BY {columna} {direccion}, mc.IdMovimientoCaja {direccion}"

    # La consulta solo incorpora identificadores validados.
    consulta = (
        _MOVIMIENTOS + orden_sql + " OFFSET :offset ROWS FETCH NEXT :limite ROWS ONLY"
    )

    filas = _filas(
        conn,
        consulta,
        {"id": id_jornada, "offset": offset, "limite": limite},
    )
    return filas, int(total)


# --- CAJ-14: consultar cuadre ----------


def obtener_cuadre_de_jornada(
    conn: Connection,
    id_jornada: int,
    bloquear: bool = False,
) -> Fila | None:
    consulta_normal = """
        SELECT TOP (1)
            IdCuadreCaja, IdJornadaCaja, IdUsuario, FechaHoraCuadre,
            SaldoInicial, TotalDotaciones, TotalDepositos, TotalRetiros,
            TotalPagos, TotalDevolucionesBoveda, SaldoFinalFisico,
            DiferenciaDinero, EstadoCuadre, IdAutorizadoPor,
            IdFechaContable, Observaciones
        FROM Caja.CuadreCaja
        WHERE IdJornadaCaja = :id
        ORDER BY IdCuadreCaja
    """

    consulta_bloqueada = """
        SELECT TOP (1)
            IdCuadreCaja, IdJornadaCaja, IdUsuario, FechaHoraCuadre,
            SaldoInicial, TotalDotaciones, TotalDepositos, TotalRetiros,
            TotalPagos, TotalDevolucionesBoveda, SaldoFinalFisico,
            DiferenciaDinero, EstadoCuadre, IdAutorizadoPor,
            IdFechaContable, Observaciones
        FROM Caja.CuadreCaja WITH (UPDLOCK, HOLDLOCK)
        WHERE IdJornadaCaja = :id
        ORDER BY IdCuadreCaja
    """

    consulta = consulta_bloqueada if bloquear else consulta_normal
    return _fila(conn, consulta, {"id": id_jornada})


# --- CAJ-06: cancelación de jornada ----------


def jornada_tiene_actividad(
    conn: Connection,
    id_jornada: int,
) -> bool:
    """Comprueba dotaciones, movimientos, transacciones y cuadre."""
    fila = _fila(
        conn,
        """
        SELECT CASE WHEN
            EXISTS (
                SELECT 1
                FROM Caja.DotacionesCaja
                WHERE IdJornadaCaja = :id
            )
            OR EXISTS (
                SELECT 1
                FROM Caja.MovimientosCaja
                WHERE IdJornadaCaja = :id
            )
            OR EXISTS (
                SELECT 1
                FROM Caja.CuadreCaja
                WHERE IdJornadaCaja = :id
            )
            OR EXISTS (
                SELECT 1
                FROM Caja.DevolucionesCaja
                WHERE IdJornadaCaja = :id
            )
            OR EXISTS (
                SELECT 1
                FROM Transacciones.Transaccion
                WHERE IdJornadaCaja = :id
            )
        THEN 1 ELSE 0 END AS Actividad
        """,
        {"id": id_jornada},
    )

    return bool(fila and fila["Actividad"])


def cancelar_jornada(
    conn: Connection,
    id_jornada: int,
    motivo: str,
) -> bool:
    resultado = conn.execute(
        text(
            """
            UPDATE Caja.JornadasCaja
            SET
                Estado = 'CANCELADA',
                FechaHoraCierre = CAST(
                    SYSDATETIMEOFFSET()
                    AT TIME ZONE 'SA Pacific Standard Time'
                    AS datetime2
                ),
                Observacion = :motivo
            WHERE
                IdJornadaCaja = :id
                AND Estado = 'ABIERTA'
            """
        ),
        {
            "id": id_jornada,
            "motivo": motivo,
        },
    )

    return resultado.rowcount == 1


# --- CAJ-03: apertura de jornada ----------


def obtener_caja_fisica(
    conn: Connection,
    id_caja: int,
) -> Fila | None:
    return _fila(
        conn,
        """
        SELECT IdCajaFisica, IdAgencia, CodigoCaja, Estado
        FROM Caja.CajaFisica WITH (UPDLOCK, HOLDLOCK)
        WHERE IdCajaFisica = :id
        """,
        {"id": id_caja},
    )


def cajero_asignado(
    conn: Connection,
    id_usuario: int,
    id_agencia: str,
) -> bool:
    fila = _fila(
        conn,
        """
        SELECT TOP (1) 1 AS Asignado
        FROM Caja.CajerosAsignadosAgencia
        WHERE IdUsuario = :id_usuario
          AND IdAgencia = :id_agencia
          AND Estado = 1
          AND FechaInicio <= CAST(
              SYSDATETIMEOFFSET()
              AT TIME ZONE 'SA Pacific Standard Time'
              AS datetime2
          )
          AND (
              FechaFin IS NULL
              OR FechaFin >= CAST(
                  SYSDATETIMEOFFSET()
                  AT TIME ZONE 'SA Pacific Standard Time'
                  AS datetime2
              )
          )
        """,
        {
            "id_usuario": id_usuario,
            "id_agencia": id_agencia,
        },
    )

    return fila is not None


def jornada_abierta_de_usuario(
    conn: Connection,
    id_usuario: int,
    bloquear: bool = True,
) -> Fila | None:
    if bloquear:
        consulta = """
            SELECT TOP (1) *
            FROM Caja.JornadasCaja WITH (UPDLOCK, HOLDLOCK)
            WHERE IdUsuario = :id_usuario
              AND Estado = 'ABIERTA'
            ORDER BY IdJornadaCaja DESC
        """
    else:
        consulta = """
            SELECT TOP (1) *
            FROM Caja.JornadasCaja
            WHERE IdUsuario = :id_usuario
              AND Estado = 'ABIERTA'
            ORDER BY IdJornadaCaja DESC
        """

    return _fila(
        conn,
        consulta,
        {"id_usuario": id_usuario},
    )


def jornada_abierta_de_caja(
    conn: Connection,
    id_caja: int,
) -> Fila | None:
    return _fila(
        conn,
        """
        SELECT TOP (1) *
        FROM Caja.JornadasCaja WITH (UPDLOCK, HOLDLOCK)
        WHERE IdCajaFisica = :id_caja
          AND Estado = 'ABIERTA'
        ORDER BY IdJornadaCaja DESC
        """,
        {"id_caja": id_caja},
    )


def insertar_jornada(
    conn: Connection,
    id_usuario: int,
    id_caja: int,
    id_agencia: str,
    dinero_inicial: Any,
    observacion: str | None,
) -> int:
    resultado = conn.execute(
        text(
            """
            SET NOCOUNT ON;

            DECLARE @ids TABLE (Id int);

            INSERT INTO Caja.JornadasCaja (
                IdUsuario,
                IdCajaFisica,
                IdAgencia,
                FechaHoraApertura,
                DineroInicial,
                Estado,
                Observacion
            )
            OUTPUT INSERTED.IdJornadaCaja INTO @ids
            VALUES (
                :id_usuario,
                :id_caja,
                :id_agencia,
                CAST(
                    SYSDATETIMEOFFSET()
                    AT TIME ZONE 'SA Pacific Standard Time'
                    AS datetime2
                ),
                :dinero_inicial,
                'ABIERTA',
                :observacion
            );

            SELECT Id FROM @ids;
            """
        ),
        {
            "id_usuario": id_usuario,
            "id_caja": id_caja,
            "id_agencia": id_agencia,
            "dinero_inicial": dinero_inicial,
            "observacion": observacion,
        },
    ).first()

    if resultado is None:
        raise RuntimeError("La BD no devolvió el id de la jornada")

    return int(resultado[0])


# --- CAJ-07: dotación ----------


def id_fecha_contable(conn: Connection) -> int | None:
    """Obtiene el identificador de la fecha contable vigente."""
    valor = conn.execute(
        text("SELECT Contabilidad.fn_IdFechaContable(GETDATE())")
    ).scalar()

    return int(valor) if valor is not None else None


def registrar_dotacion(
    conn: Connection,
    id_jornada: int,
    id_boveda: int,
    autorizado_por: int,
    tipo: str,
    desglose_json: str,
    observacion: str | None,
    id_fecha_contable: int,
) -> Fila:
    return ejecutar_con_salidas(
        conn,
        """
        SET NOCOUNT ON;

        DECLARE @IdDotacionCaja int,
                @IdMovimientoBoveda bigint,
                @BovedaBajoMinimo bit;

        EXEC Caja.usp_RegistrarDotacionCaja
            @IdJornadaCaja = ?,
            @IdBoveda = ?,
            @AutorizadoPor = ?,
            @TipoDotacion = ?,
            @DesgloseJson = ?,
            @Observacion = ?,
            @IdFechaContable = ?,
            @IdDotacionCaja = @IdDotacionCaja OUTPUT,
            @IdMovimientoBoveda = @IdMovimientoBoveda OUTPUT,
            @BovedaBajoMinimo = @BovedaBajoMinimo OUTPUT;

        SELECT
            @IdDotacionCaja AS IdDotacionCaja,
            @IdMovimientoBoveda AS IdMovimientoBoveda,
            @BovedaBajoMinimo AS BovedaBajoMinimo;
        """,
        (
            id_jornada,
            id_boveda,
            autorizado_por,
            tipo,
            desglose_json,
            observacion,
            id_fecha_contable,
        ),
    )


def obtener_dotacion(
    conn: Connection,
    id_dotacion: int,
) -> Fila | None:
    return _fila(
        conn,
        """
        SELECT *
        FROM Caja.DotacionesCaja
        WHERE IdDotacionCaja = :id
        """,
        {"id": id_dotacion},
    )
