"""Persistencia de solicitudes. Las transacciones se controlan en service."""

from typing import Any

from sqlalchemy import Connection, bindparam, text

Fila = dict[str, Any]
_SOLICITUD = """
SELECT IdSolicitudMovimiento AS id_solicitud_movimiento, IdBoveda AS id_boveda,
       IdBovedaContraparte AS id_boveda_contraparte, RTRIM(IdAgencia) AS id_agencia,
       TipoMovimiento AS tipo_movimiento, Monto AS monto,
       IdUsuarioSolicitante AS id_usuario_solicitante, FechaSolicitud AS fecha_solicitud,
       Estado AS estado, Observaciones AS observaciones,
       IdUsuarioResolucion AS id_usuario_resolucion, FechaResolucion AS fecha_resolucion,
       MotivoResolucion AS motivo_resolucion, HuellaPeticion AS huella_peticion
FROM Boveda.SolicitudMovimientoBoveda
"""


def obtener(conn: Connection, id_solicitud: int, bloquear: bool = False) -> Fila | None:
    bloqueo = " WITH (UPDLOCK, HOLDLOCK)" if bloquear else ""
    fila = (
        conn.execute(
            text(_SOLICITUD + bloqueo + " WHERE IdSolicitudMovimiento = :id"),
            {"id": id_solicitud},
        )
        .mappings()
        .first()
    )
    return dict(fila) if fila is not None else None


def repeticion(conn: Connection, actor: int, clave: str) -> Fila | None:
    fila = (
        conn.execute(
            text(
                _SOLICITUD
                + " WITH (UPDLOCK, HOLDLOCK) WHERE IdUsuarioSolicitante = :actor AND ClaveIdempotencia = :clave"
            ),
            {"actor": actor, "clave": clave},
        )
        .mappings()
        .first()
    )
    return dict(fila) if fila is not None else None


def listar(
    conn: Connection, agencia: str | None, estado: str | None, page: int, page_size: int
) -> tuple[list[Fila], int]:
    params = {
        "agencia": agencia,
        "estado": estado,
        "offset": (page - 1) * page_size,
        "size": page_size,
    }
    filtros = " WHERE (:agencia IS NULL OR IdAgencia = :agencia) AND (:estado IS NULL OR Estado = :estado)"
    contar = "SELECT COUNT_BIG(*) FROM Boveda.SolicitudMovimientoBoveda"
    total = int(conn.execute(text(contar + filtros), params).scalar_one())
    filas = conn.execute(
        text(
            _SOLICITUD
            + filtros
            + " ORDER BY IdSolicitudMovimiento DESC OFFSET :offset ROWS FETCH NEXT :size ROWS ONLY"
        ),
        params,
    ).mappings()
    return [dict(f) for f in filas], total


def detalles(conn: Connection, ids: list[int]) -> dict[int, list[Fila]]:
    resultado: dict[int, list[Fila]] = {i: [] for i in ids}
    if not ids:
        return resultado
    consulta = text("""
        SELECT IdSolicitudMovimiento AS id_solicitud_movimiento,
               IdDenominacion AS id_denominacion, Cantidad AS cantidad, ValorUnitario AS valor_unitario
        FROM Boveda.SolicitudMovimientoBovedaDenominacion
        WHERE IdSolicitudMovimiento IN :ids ORDER BY IdDenominacion
    """).bindparams(bindparam("ids", expanding=True))
    for fila in conn.execute(consulta, {"ids": ids}).mappings():
        resultado[fila["id_solicitud_movimiento"]].append(dict(fila))
    return resultado


def movimientos(conn: Connection, ids: list[int]) -> dict[int, list[int]]:
    resultado: dict[int, list[int]] = {i: [] for i in ids}
    if not ids:
        return resultado
    consulta = text("""
        SELECT IdSolicitudMovimiento, IdMovimiento FROM Boveda.MovimientoBoveda
        WHERE IdSolicitudMovimiento IN :ids ORDER BY IdMovimiento
    """).bindparams(bindparam("ids", expanding=True))
    for fila in conn.execute(consulta, {"ids": ids}).mappings():
        resultado[fila["IdSolicitudMovimiento"]].append(fila["IdMovimiento"])
    return resultado


def crear(conn: Connection, datos: Fila, detalle: list[Fila]) -> int:
    id_solicitud = int(
        conn.execute(
            text("""
        INSERT INTO Boveda.SolicitudMovimientoBoveda
            (IdBoveda, IdBovedaContraparte, IdAgencia, TipoMovimiento, Monto,
             IdUsuarioSolicitante, FechaSolicitud, Estado, Observaciones, ClaveIdempotencia, HuellaPeticion)
        OUTPUT INSERTED.IdSolicitudMovimiento
        VALUES (:boveda, :contraparte, :agencia, :tipo, :monto, :actor, :ahora,
                'PENDIENTE', :observaciones, :clave, :huella)
    """),
            datos,
        ).scalar_one()
    )
    conn.execute(
        text("""
        INSERT INTO Boveda.SolicitudMovimientoBovedaDenominacion
            (IdSolicitudMovimiento, IdDenominacion, Cantidad, ValorUnitario)
        VALUES (:solicitud, :id_denominacion, :cantidad, :valor_unitario)
    """),
        [{**f, "solicitud": id_solicitud} for f in detalle],
    )
    return id_solicitud


def resolver(
    conn: Connection,
    id_solicitud: int,
    estado: str,
    actor: int,
    ahora,
    motivo: str | None,
) -> None:
    conn.execute(
        text("""
        UPDATE Boveda.SolicitudMovimientoBoveda SET Estado = :estado,
            IdUsuarioResolucion = :actor, FechaResolucion = :ahora, MotivoResolucion = :motivo
        WHERE IdSolicitudMovimiento = :id AND Estado = 'PENDIENTE'
    """),
        {
            "id": id_solicitud,
            "estado": estado,
            "actor": actor,
            "ahora": ahora,
            "motivo": motivo,
        },
    )


def vincular(conn: Connection, id_solicitud: int, movimientos_ids: list[int]) -> None:
    consulta = text(
        "UPDATE Boveda.MovimientoBoveda SET IdSolicitudMovimiento = :solicitud WHERE IdMovimiento IN :ids"
    ).bindparams(bindparam("ids", expanding=True))
    conn.execute(consulta, {"solicitud": id_solicitud, "ids": movimientos_ids})
