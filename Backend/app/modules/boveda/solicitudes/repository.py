"""Persistencia de solicitudes. Las transacciones se controlan en service."""

from contextlib import contextmanager
from typing import Any

from sqlalchemy import Connection, bindparam, text

Fila = dict[str, Any]
_SOLICITUD = """
SELECT IdSolicitudMovimiento AS id_solicitud_movimiento, IdBoveda AS id_boveda,
       IdBovedaContraparte AS id_boveda_contraparte, RTRIM(IdAgencia) AS id_agencia,
       RTRIM(IdAgenciaDestino) AS id_agencia_destino,
       TipoMovimiento AS tipo_movimiento, Monto AS monto,
       IdUsuarioSolicitante AS id_usuario_solicitante, FechaSolicitud AS fecha_solicitud,
       Estado AS estado, Observaciones AS observaciones,
       IdUsuarioResolucion AS id_usuario_resolucion, FechaResolucion AS fecha_resolucion,
       MotivoResolucion AS motivo_resolucion, HuellaPeticion AS huella_peticion,
       IdUsuarioAnulacion AS id_usuario_anulacion, FechaAnulacion AS fecha_anulacion,
       MotivoAnulacion AS motivo_anulacion,
       IdUsuarioDespacho AS id_usuario_despacho, FechaDespacho AS fecha_despacho,
       NumeroGuia AS numero_guia, Precinto AS precinto,
       IdUsuarioConfirmacion AS id_usuario_confirmacion, FechaConfirmacion AS fecha_confirmacion,
       MontoConfirmado AS monto_confirmado, MontoConfirmado - Monto AS diferencia,
       ActaNovedad AS acta_novedad, ComprobanteBanco AS comprobante_banco,
       IdAsientoDespacho AS id_asiento_despacho, IdAsientoConfirmacion AS id_asiento_confirmacion,
       IdAsientoNovedad AS id_asiento_novedad, IdCuentaTransito AS id_cuenta_transito,
       UsaPlantillaVersionada AS usa_plantilla_versionada
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


def destinos(conn: Connection, origen: int) -> list[Fila]:
    filas = conn.execute(
        text("""
            SELECT b.IdBoveda AS id_boveda, b.CodigoBoveda AS codigo_boveda,
                   RTRIM(b.IdAgencia) AS id_agencia
            FROM Boveda.Boveda b
            JOIN Organizacion.Agencia a ON a.IdAgencia = b.IdAgencia
            WHERE b.IdBoveda <> :origen AND b.Estado = 'A' AND a.Estado = 'A'
            ORDER BY b.IdAgencia, b.CodigoBoveda, b.IdBoveda
        """),
        {"origen": origen},
    ).mappings()
    return [dict(f) for f in filas]


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
    filtros = """
        WHERE (:agencia IS NULL OR IdAgencia = :agencia OR IdAgenciaDestino = :agencia)
          AND (:estado IS NULL OR Estado = :estado)
    """
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


def conteos(conn: Connection, ids: list[int]) -> dict[int, list[Fila]]:
    resultado: dict[int, list[Fila]] = {i: [] for i in ids}
    if not ids:
        return resultado
    consulta = text("""
        SELECT IdSolicitudMovimiento AS id_solicitud_movimiento, IdDenominacion AS id_denominacion,
               Cantidad AS cantidad, ValorUnitario AS valor_unitario
        FROM Boveda.SolicitudMovimientoBovedaConteo
        WHERE IdSolicitudMovimiento IN :ids ORDER BY IdDenominacion
    """).bindparams(bindparam("ids", expanding=True))
    for fila in conn.execute(consulta, {"ids": ids}).mappings():
        resultado[fila["id_solicitud_movimiento"]].append(dict(fila))
    return resultado


def guardar_conteo(conn: Connection, id_solicitud: int, detalle: list[Fila]) -> None:
    if detalle:
        conn.execute(
            text("""
                INSERT INTO Boveda.SolicitudMovimientoBovedaConteo
                    (IdSolicitudMovimiento, IdDenominacion, Cantidad, ValorUnitario)
                VALUES (:solicitud, :id_denominacion, :cantidad, :valor_unitario)
            """),
            [{**f, "solicitud": id_solicitud} for f in detalle],
        )


def cupo_ocupado(conn: Connection, agencia: str) -> bool:
    return (
        conn.execute(
            text("""
            SELECT IdSolicitudMovimiento FROM Boveda.CupoSolicitudMovimiento WITH (UPDLOCK, HOLDLOCK)
            WHERE IdAgencia = :agencia
        """),
            {"agencia": agencia},
        ).scalar_one_or_none()
        is not None
    )


def reservar_cupo(conn: Connection, solicitud: int, agencias: list[str]) -> None:
    conn.execute(
        text("""
            INSERT INTO Boveda.CupoSolicitudMovimiento(IdAgencia, IdSolicitudMovimiento)
            VALUES (:agencia, :solicitud)
        """),
        [{"agencia": agencia, "solicitud": solicitud} for agencia in agencias],
    )


def liberar_cupo(conn: Connection, solicitud: int) -> None:
    conn.execute(
        text(
            "DELETE FROM Boveda.CupoSolicitudMovimiento WHERE IdSolicitudMovimiento = :id"
        ),
        {"id": solicitud},
    )


@contextmanager
def afectar_reserva(conn: Connection, solicitud: int):
    consulta = text(
        "EXEC sys.sp_set_session_context @key=N'BovedaSolicitudMovimiento', @value=:id"
    )
    conn.execute(consulta, {"id": solicitud})
    try:
        yield
    finally:
        try:
            conn.execute(consulta, {"id": None})
        except BaseException:
            # SESSION_CONTEXT sobrevive al rollback y no debe volver al pool.
            conn.invalidate()
            raise


def crear(conn: Connection, datos: Fila, detalle: list[Fila]) -> int:
    id_solicitud = int(
        conn.execute(
            text("""
        INSERT INTO Boveda.SolicitudMovimientoBoveda
            (IdBoveda, IdBovedaContraparte, IdAgencia, IdAgenciaDestino, TipoMovimiento, Monto,
             IdUsuarioSolicitante, FechaSolicitud, Estado, Observaciones, ClaveIdempotencia, HuellaPeticion)
        OUTPUT INSERTED.IdSolicitudMovimiento
        VALUES (:boveda, :contraparte, :agencia, :agencia_destino, :tipo, :monto, :actor, :ahora,
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
    cuenta_transito: int | None = None,
    usa_version: bool | None = None,
) -> None:
    conn.execute(
        text("""
        UPDATE Boveda.SolicitudMovimientoBoveda SET Estado = :estado,
            IdUsuarioResolucion = :actor, FechaResolucion = :ahora, MotivoResolucion = :motivo,
            IdCuentaTransito = :cuenta_transito, UsaPlantillaVersionada = :usa_version
        WHERE IdSolicitudMovimiento = :id AND Estado = 'PENDIENTE'
    """),
        {
            "id": id_solicitud,
            "estado": estado,
            "actor": actor,
            "ahora": ahora,
            "motivo": motivo,
            "cuenta_transito": cuenta_transito,
            "usa_version": usa_version,
        },
    )


def despachar(conn: Connection, datos: Fila) -> None:
    conn.execute(
        text("""
            UPDATE Boveda.SolicitudMovimientoBoveda SET Estado = 'DESPACHADO',
                IdUsuarioDespacho = :actor, FechaDespacho = :ahora,
                NumeroGuia = :guia, Precinto = :precinto, IdAsientoDespacho = :asiento
            WHERE IdSolicitudMovimiento = :solicitud AND Estado = 'APROBADO'
        """),
        datos,
    )


def anular(conn: Connection, solicitud: int, actor: int, ahora, motivo: str) -> None:
    conn.execute(
        text("""
            UPDATE Boveda.SolicitudMovimientoBoveda SET Estado = 'ANULADA',
                IdUsuarioAnulacion = :actor, FechaAnulacion = :ahora, MotivoAnulacion = :motivo
            WHERE IdSolicitudMovimiento = :solicitud AND Estado = 'APROBADO'
        """),
        {"solicitud": solicitud, "actor": actor, "ahora": ahora, "motivo": motivo},
    )


def confirmar(conn: Connection, datos: Fila) -> None:
    conn.execute(
        text("""
            UPDATE Boveda.SolicitudMovimientoBoveda SET Estado = :estado,
                IdUsuarioConfirmacion = :actor, FechaConfirmacion = :ahora,
                MontoConfirmado = :monto, ActaNovedad = :acta, ComprobanteBanco = :comprobante,
                NumeroGuia = COALESCE(NumeroGuia, :guia), Precinto = COALESCE(Precinto, :precinto),
                IdAsientoConfirmacion = :asiento, IdAsientoNovedad = :novedad
            WHERE IdSolicitudMovimiento = :solicitud AND Estado IN ('APROBADO', 'DESPACHADO')
        """),
        datos,
    )


def vincular(conn: Connection, id_solicitud: int, movimientos_ids: list[int]) -> None:
    consulta = text(
        "UPDATE Boveda.MovimientoBoveda SET IdSolicitudMovimiento = :solicitud WHERE IdMovimiento IN :ids"
    ).bindparams(bindparam("ids", expanding=True))
    conn.execute(consulta, {"solicitud": id_solicitud, "ids": movimientos_ids})
