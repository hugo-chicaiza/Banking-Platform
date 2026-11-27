"""Transiciones programadas de débito en una transacción con su historial."""

from datetime import date, timedelta

from sqlalchemy import Connection, text

from app.core.database.db import get_engine
from app.core.security import audit
from app.core.tareas.ejecutor import Conteo
from app.modules.tarjetas import ciclo


def vencer_tarjetas(conn: Connection, fecha: date) -> int:
    return int(
        conn.execute(
            text("""
        SET NOCOUNT ON;
        DECLARE @cambios TABLE (IdTarjeta int, EstadoAnterior varchar(20));
        UPDATE t WITH (UPDLOCK) SET Estado='Vencida'
        OUTPUT inserted.IdTarjeta, deleted.Estado INTO @cambios
        FROM Tarjeta.Tarjeta t
        WHERE t.TipoTarjeta='Debito' AND t.Estado IN ('Activa','Inactiva','Bloqueada')
          AND t.FechaExpiracion < :fecha;
        INSERT Tarjeta.TarjetaHis
            (IdTarjeta,TipoEvento,EstadoAnterior,EstadoActual,Descripcion,RealizadoPor)
        SELECT IdTarjeta,'CambioEstado',EstadoAnterior,'Vencida',N'TAR_VENCIDA',0
        FROM @cambios;
        SELECT COUNT(*) FROM @cambios;
    """),
            {"fecha": fecha},
        ).scalar_one()
    )


def anular_tarjetas_no_retiradas(conn: Connection, corte: date) -> int:
    return int(
        conn.execute(
            text("""
        SET NOCOUNT ON;
        DECLARE @cambios TABLE (IdTarjeta int);
        UPDATE t WITH (UPDLOCK) SET Estado='Anulada', MotivoEstado='NO_RETIRADA'
        OUTPUT inserted.IdTarjeta INTO @cambios
        FROM Tarjeta.Tarjeta t
        WHERE t.TipoTarjeta='Debito' AND t.Estado='Generada' AND t.FechaEmision<=:corte
          AND t.EntregaVerificadaEn IS NULL
          AND NOT EXISTS (
            SELECT 1 FROM Tarjeta.EnviosTarjeta e WHERE e.IdTarjeta=t.IdTarjeta AND e.DespachadoEn IS NOT NULL
          );
        INSERT Tarjeta.TarjetaHis
            (IdTarjeta,TipoEvento,EstadoAnterior,EstadoActual,Descripcion,RealizadoPor)
        SELECT IdTarjeta,'Anulacion','Generada','Anulada',N'Tarjeta no retirada',0
        FROM @cambios;
        SELECT COUNT(*) FROM @cambios;
    """),
            {"corte": corte},
        ).scalar_one()
    )


def _resultado(evento: str, cambios: int) -> Conteo:
    if cambios:
        audit.registrar(
            audit.EventoAuditoria(
                accion=evento,
                tabla="Tarjeta.Tarjeta",
                id_registro=None,
                resultado="Exitoso",
                usuario=None,
                ip=None,
                descripcion=f"Tarjetas modificadas: {cambios}",
            )
        )
    return Conteo(procesados=cambios, modificados=cambios)


def vencer() -> Conteo:
    with get_engine("cooperativa").begin() as conn:
        cambios = vencer_tarjetas(conn, ciclo.hoy())
    return _resultado("TAR_VENCIDA", cambios)


def anular_no_retiradas() -> Conteo:
    fecha = ciclo.hoy()
    with get_engine("cooperativa").begin() as conn:
        corte = fecha - timedelta(days=ciclo.dias(conn, ciclo.PLAZO_RETIRO, fecha))
        cambios = anular_tarjetas_no_retiradas(conn, corte)
    return _resultado("TAR_ANULAR_NO_RETIRADAS", cambios)
