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
