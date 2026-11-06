"""SQL de Transacciones. Solo consultas parametrizadas con fragmentos fijos."""

from typing import Any

from sqlalchemy import Connection, text

Fila = dict[str, Any]

_COLUMNAS = """
t.IdTransaccion, t.NumeroComprobante, t.RegistroUnico, t.MTI, t.STAN, t.RRN,
t.TipoOperacion, t.TipoTransaccion, t.IdCuenta, t.IdCuentaDestino, t.IdTarjeta,
t.IdCanal, t.IdATM AS IdTerminal, t.IdAgencia, t.IdJornadaCaja,
t.IdTransaccionRelacionada, t.Monto, t.CodigoRespuesta, t.Estado,
t.IdFechaContable, t.FechaHoraSistema, t.CreadoPor, t.NumeroAutorizacion,
COALESCE(t.IdAgencia, c.IdAgencia) AS AgenciaOperacion
"""
_ORIGEN = """
FROM Transacciones.Transaccion t
JOIN Cuentas.Cuenta c ON c.IdCuenta = t.IdCuenta
"""

# --- TRX-01 consulta -----------------------------------------------------------------

_FILTROS = {
    "id_cuenta": " AND t.IdCuenta = :id_cuenta",
    "tipo_transaccion": " AND t.TipoTransaccion = :tipo_transaccion",
    "estado": " AND t.Estado = :estado",
    "id_canal": " AND t.IdCanal = :id_canal",
    "id_agencia": " AND t.IdAgencia = :id_agencia",
    "desde": " AND t.FechaHoraSistema >= :desde",
    "hasta": " AND t.FechaHoraSistema < :hasta",
    # SUPERVISOR: solo su agencia (de la transacción o, si no tiene, de la cuenta)
    "alcance": " AND COALESCE(t.IdAgencia, c.IdAgencia) = :alcance",
}
ORDEN = {
    "fechaHoraSistema": "t.FechaHoraSistema",
    "monto": "t.Monto",
    "idTransaccion": "t.IdTransaccion",
}


def listar_transacciones(
    conn: Connection,
    filtros: dict[str, Any],
    orden: tuple[str, str],
    offset: int,
    limite: int,
) -> tuple[list[Fila], int]:
    parametros = {k: v for k, v in filtros.items() if v is not None}
    where = " WHERE 1 = 1" + "".join(_FILTROS[k] for k in parametros)
    columna = ORDEN[orden[0]]
    direccion = "DESC" if orden[1] == "desc" else "ASC"
    total = conn.execute(
        text("SELECT COUNT_BIG(*)" + _ORIGEN + where),  # fijo
        parametros,
    ).scalar_one()
    filas = conn.execute(
        text(
            "SELECT"  # fragmentos fijos de este módulo
            + _COLUMNAS
            + _ORIGEN
            + where
            + f" ORDER BY {columna} {direccion}, t.IdTransaccion {direccion}"
            + " OFFSET :offset ROWS FETCH NEXT :limite ROWS ONLY"
        ),
        {**parametros, "offset": offset, "limite": limite},
    ).mappings()
    return [dict(fila) for fila in filas], int(total)
