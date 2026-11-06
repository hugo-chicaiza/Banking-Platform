from datetime import date, timedelta
from typing import Any

from sqlalchemy import Connection, text

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
