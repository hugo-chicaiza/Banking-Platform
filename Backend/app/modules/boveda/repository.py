"""SQL parametrizado de Bóveda; la transacción pertenece al servicio."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, bindparam, text

Fila = dict[str, Any]
ORDEN_MOVIMIENTOS = {
    "idMovimiento": "IdMovimiento",
    "fechaMovimiento": "FechaMovimiento",
    "tipoMovimiento": "TipoMovimiento",
    "naturaleza": "Naturaleza",
    "monto": "Monto",
}
_BOVEDA = """
SELECT IdBoveda AS id_boveda, CodigoBoveda AS codigo_boveda,
       TipoBoveda AS tipo_boveda, RTRIM(IdAgencia) AS id_agencia,
       IdBovedaSuperior AS id_boveda_superior, LimiteMaximo AS limite_maximo,
       LimiteMinimo AS limite_minimo, SaldoActual AS saldo_actual, Estado AS estado
FROM Boveda.Boveda
"""
_MOVIMIENTO = """
SELECT IdMovimiento AS id_movimiento, IdBoveda AS id_boveda,
       IdBovedaContraparte AS id_boveda_contraparte, TipoMovimiento AS tipo_movimiento,
       Naturaleza AS naturaleza, Monto AS monto, SaldoAnterior AS saldo_anterior,
       SaldoPosterior AS saldo_posterior, AutorizadoPor AS autorizado_por,
       IdUsuarioMovimiento AS id_usuario_movimiento,
       IdMovimientoRelacionado AS id_movimiento_relacionado,
       FechaMovimiento AS fecha_movimiento, Observaciones AS observaciones,
       IdAsientoContable AS id_asiento_contable
FROM Boveda.MovimientoBoveda
"""
_ARQUEO = """
SELECT IdArqueoBoveda AS id_arqueo_boveda, IdBoveda AS id_boveda,
       FechaHoraArqueo AS fecha_hora_arqueo, TipoArqueo AS tipo_arqueo,
       IdUsuarioArqueador AS id_usuario_arqueador, IdUsuarioTestigo AS id_usuario_testigo,
       Estado AS estado, IdMovimientoAjuste AS id_movimiento_ajuste,
       Observaciones AS observaciones, SaldoTeorico AS saldo_teorico,
       SaldoFisico AS saldo_fisico, IdMovimientoCorte AS id_movimiento_corte,
       IdUsuarioAprobador AS id_usuario_aprobador, FechaHoraAprobacion AS fecha_hora_aprobacion
FROM Boveda.ArqueoBoveda
"""
_CONTAR_MOVIMIENTOS = "SELECT COUNT_BIG(*) FROM Boveda.MovimientoBoveda"


def _filas(conn: Connection, sql: str, params: Fila) -> list[Fila]:
    return [dict(f) for f in conn.execute(text(sql), params).mappings()]


def _fila(conn: Connection, sql: str, params: Fila) -> Fila | None:
    fila = conn.execute(text(sql), params).mappings().first()
    return dict(fila) if fila is not None else None


def listar_bovedas(
    conn: Connection, agencia: str | None, tipo: str | None
) -> list[Fila]:
    return _filas(
        conn,
        _BOVEDA
        + " WITH (HOLDLOCK)"
        + """
        WHERE (:agencia IS NULL OR IdAgencia = :agencia)
          AND (:tipo IS NULL OR TipoBoveda = :tipo) ORDER BY IdBoveda
        """,
        {"agencia": agencia, "tipo": tipo},
    )


def obtener_boveda(
    conn: Connection, id_boveda: int, bloquear: bool = False
) -> Fila | None:
    bloqueo = " WITH (UPDLOCK, HOLDLOCK)" if bloquear else ""
    return _fila(conn, _BOVEDA + bloqueo + " WHERE IdBoveda = :id", {"id": id_boveda})


def inventarios(conn: Connection, ids: list[int]) -> dict[int, list[Fila]]:
    resultado: dict[int, list[Fila]] = {i: [] for i in ids}
    for inicio in range(0, len(ids), 1000):
        consulta = text("""
            SELECT bd.IdBoveda AS id_boveda, bd.IdDenominacion AS id_denominacion,
                   bd.CantidadActual AS cantidad_actual, d.Valor AS valor
            FROM Boveda.BovedaDenominacion bd
            JOIN Catalogo.Denominacion d ON d.IdDenominacion = bd.IdDenominacion
            WHERE bd.IdBoveda IN :ids ORDER BY bd.IdDenominacion
        """).bindparams(bindparam("ids", expanding=True))
        for f in conn.execute(
            consulta, {"ids": ids[inicio : inicio + 1000]}
        ).mappings():
            resultado[f["id_boveda"]].append(dict(f))
    return resultado


def denominaciones(conn: Connection, ids: list[int]) -> dict[int, Fila]:
    consulta = text("""
        SELECT IdDenominacion AS id_denominacion, Valor AS valor, Estado AS estado
        FROM Catalogo.Denominacion WITH (HOLDLOCK) WHERE IdDenominacion IN :ids
    """).bindparams(bindparam("ids", expanding=True))
    return {
        f["id_denominacion"]: dict(f)
        for f in conn.execute(consulta, {"ids": ids}).mappings()
    }


def ultimo_movimiento(conn: Connection, id_boveda: int) -> int:
    return int(
        conn.execute(
            text(
                "SELECT COALESCE(MAX(IdMovimiento), 0) FROM Boveda.MovimientoBoveda WHERE IdBoveda = :id"
            ),
            {"id": id_boveda},
        ).scalar_one()
    )


def obtener_movimiento(conn: Connection, id_movimiento: int) -> Fila:
    fila = _fila(conn, _MOVIMIENTO + " WHERE IdMovimiento = :id", {"id": id_movimiento})
    if fila is None:
        raise RuntimeError("No se encontró el movimiento recién registrado")
    return fila


def desgloses_movimientos(conn: Connection, ids: list[int]) -> dict[int, list[Fila]]:
    resultado: dict[int, list[Fila]] = {i: [] for i in ids}
    if ids:
        consulta = text("""
            SELECT IdMovimiento AS id_movimiento, IdDenominacion AS id_denominacion, Cantidad AS cantidad
            FROM Boveda.MovimientoBovedaDenominacion WHERE IdMovimiento IN :ids ORDER BY IdDenominacion
        """).bindparams(bindparam("ids", expanding=True))
        for f in conn.execute(consulta, {"ids": ids}).mappings():
            resultado[f["id_movimiento"]].append(dict(f))
    return resultado


def listar_movimientos(
    conn: Connection,
    id_boveda: int,
    tipo: str | None,
    desde: date | None,
    hasta: date | None,
    page: int,
    page_size: int,
    sort: str,
) -> tuple[list[Fila], int]:
    campo, direccion = sort.split(",")
    columna = ORDEN_MOVIMIENTOS[campo]
    # Solo estos dos literales pueden llegar al SQL; nunca se interpola texto libre.
    orden = "ASC" if direccion == "asc" else "DESC"
    filtros = """ WHERE IdBoveda = :id AND (:tipo IS NULL OR TipoMovimiento = :tipo)
        AND (:desde IS NULL OR FechaMovimiento >= :desde)
        AND (:hasta IS NULL OR FechaMovimiento < :hasta) """
    params = {
        "id": id_boveda,
        "tipo": tipo,
        "desde": desde,
        "hasta": hasta + timedelta(days=1) if hasta else None,
    }
    total = int(conn.execute(text(_CONTAR_MOVIMIENTOS + filtros), params).scalar_one())
    desempate = "" if campo == "idMovimiento" else ", IdMovimiento DESC"
    filas = _filas(
        conn,
        _MOVIMIENTO
        + filtros
        + f" ORDER BY {columna} {orden}{desempate} OFFSET :offset ROWS FETCH NEXT :size ROWS ONLY",
        {**params, "offset": (page - 1) * page_size, "size": page_size},
    )
    return filas, total


def crear_movimiento(conn: Connection, datos: Fila) -> int:
    return int(
        conn.execute(
            text("""
        INSERT INTO Boveda.MovimientoBoveda
            (IdBoveda, IdBovedaContraparte, TipoMovimiento, Naturaleza, Monto,
             SaldoAnterior, SaldoPosterior, AutorizadoPor, IdUsuarioMovimiento,
             Observaciones, FechaMovimiento, IdMovimientoRelacionado, IdFechaContable,
             IdArqueoBoveda, ClaveIdempotencia, HuellaPeticion)
        OUTPUT INSERTED.IdMovimiento
        VALUES (:id_boveda, :contraparte, :tipo, :naturaleza, :monto,
                :anterior, :posterior, :autorizador, :actor, :observaciones, :ahora,
                :relacionado, :fecha_contable, :arqueo, :clave, :huella)
    """),
            datos,
        ).scalar_one()
    )


def actualizar_inventario(
    conn: Connection,
    id_boveda: int,
    id_movimiento: int,
    desglose: dict[int, int],
    ingreso: bool,
    ahora: datetime,
    saldo: Decimal,
) -> None:
    for id_denominacion, cantidad in sorted(desglose.items()):
        params = {
            "boveda": id_boveda,
            "movimiento": id_movimiento,
            "denominacion": id_denominacion,
            "cantidad": cantidad,
            "delta": cantidad if ingreso else -cantidad,
            "ahora": ahora,
        }
        conn.execute(
            text("""
            INSERT INTO Boveda.MovimientoBovedaDenominacion (IdMovimiento, IdDenominacion, Cantidad)
            VALUES (:movimiento, :denominacion, :cantidad)
        """),
            params,
        )
        # El servicio ya bloqueó la bóveda; también serializa con los SP de Caja.
        conn.execute(
            text("""
            UPDATE Boveda.BovedaDenominacion SET CantidadActual = CantidadActual + :delta,
                   FechaActualizacion = :ahora
            WHERE IdBoveda = :boveda AND IdDenominacion = :denominacion;
            IF @@ROWCOUNT = 0
                INSERT INTO Boveda.BovedaDenominacion (IdBoveda, IdDenominacion, CantidadActual, FechaActualizacion)
                VALUES (:boveda, :denominacion, :delta, :ahora);
        """),
            params,
        )
    conn.execute(
        text("UPDATE Boveda.Boveda SET SaldoActual = :saldo WHERE IdBoveda = :id"),
        {"id": id_boveda, "saldo": saldo},
    )


def vincular_asiento(conn: Connection, movimiento: int, asiento: int) -> None:
    conn.execute(
        text(
            "UPDATE Boveda.MovimientoBoveda SET IdAsientoContable = :asiento WHERE IdMovimiento = :id"
        ),
        {"id": movimiento, "asiento": asiento},
    )


def relacionar_movimiento(conn: Connection, origen: int, destino: int) -> None:
    conn.execute(
        text(
            "UPDATE Boveda.MovimientoBoveda SET IdMovimientoRelacionado = :destino WHERE IdMovimiento = :origen"
        ),
        {"origen": origen, "destino": destino},
    )


def repeticion(conn: Connection, actor: int, clave: str) -> Fila | None:
    return _fila(
        conn,
        _MOVIMIENTO
        + " WITH (UPDLOCK, HOLDLOCK) WHERE IdUsuarioMovimiento = :actor AND ClaveIdempotencia = :clave",
        {"actor": actor, "clave": clave},
    )


def huella_movimiento(conn: Connection, id_movimiento: int) -> str:
    return str(
        conn.execute(
            text(
                "SELECT HuellaPeticion FROM Boveda.MovimientoBoveda WHERE IdMovimiento = :id"
            ),
            {"id": id_movimiento},
        ).scalar_one()
    )


def obtener_arqueo(
    conn: Connection, id_arqueo: int, bloquear: bool = False
) -> Fila | None:
    bloqueo = " WITH (UPDLOCK, HOLDLOCK)" if bloquear else ""
    return _fila(
        conn, _ARQUEO + bloqueo + " WHERE IdArqueoBoveda = :id", {"id": id_arqueo}
    )


def detalle_arqueo(conn: Connection, id_arqueo: int) -> list[Fila]:
    return _filas(
        conn,
        """
        SELECT IdDenominacion AS id_denominacion, Cantidad AS cantidad,
               CantidadEsperada AS cantidad_esperada, ValorUnitario AS valor
        FROM Boveda.ArqueoBovedaDenominacion WHERE IdArqueoBoveda = :id ORDER BY IdDenominacion
    """,
        {"id": id_arqueo},
    )


def ajustes_arqueo(conn: Connection, id_arqueo: int) -> list[int]:
    return list(
        conn.execute(
            text(
                "SELECT IdMovimiento FROM Boveda.MovimientoBoveda WHERE IdArqueoBoveda = :id ORDER BY IdMovimiento"
            ),
            {"id": id_arqueo},
        ).scalars()
    )


def crear_arqueo(conn: Connection, datos: Fila, detalle: list[Fila]) -> int:
    id_arqueo = int(
        conn.execute(
            text("""
        INSERT INTO Boveda.ArqueoBoveda (IdBoveda, FechaHoraArqueo, TipoArqueo,
            IdUsuarioArqueador, IdUsuarioTestigo, Estado, Observaciones,
            SaldoTeorico, SaldoFisico, IdMovimientoCorte)
        OUTPUT INSERTED.IdArqueoBoveda
        VALUES (:id_boveda, :ahora, :tipo, :actor, :testigo, 'REGISTRADO',
                :observaciones, :teorico, :fisico, :corte)
    """),
            datos,
        ).scalar_one()
    )
    for f in detalle:
        conn.execute(
            text("""
            INSERT INTO Boveda.ArqueoBovedaDenominacion
                (IdArqueoBoveda, IdDenominacion, Cantidad, CantidadEsperada, ValorUnitario)
            VALUES (:arqueo, :id_denominacion, :cantidad, :cantidad_esperada, :valor)
        """),
            {**f, "arqueo": id_arqueo},
        )
    return id_arqueo


def aprobar_arqueo(
    conn: Connection, id_arqueo: int, actor: int, ahora: datetime, ajuste: int | None
) -> None:
    conn.execute(
        text("""
        UPDATE Boveda.ArqueoBoveda SET Estado = 'APROBADO', IdUsuarioAprobador = :actor,
            FechaHoraAprobacion = :ahora, IdMovimientoAjuste = :ajuste
        WHERE IdArqueoBoveda = :id AND Estado = 'REGISTRADO'
    """),
        {"id": id_arqueo, "actor": actor, "ahora": ahora, "ajuste": ajuste},
    )
