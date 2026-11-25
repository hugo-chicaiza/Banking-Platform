from datetime import date

from sqlalchemy import Connection, text

from app.core.database.db import get_engine
from app.core.security import audit
from app.core.tareas.ejecutor import Conteo
from app.modules.parametros.service import hoy


def inactivar_cuentas(conn: Connection, fecha: date) -> Conteo:
    cambios = conn.execute(
        text("""
            SET NOCOUNT ON;
            DECLARE @Cuentas TABLE (IdCuenta int, IdAgencia char(3));
            UPDATE c WITH (UPDLOCK)
            SET Estado='Inactiva'
            OUTPUT inserted.IdCuenta, inserted.IdAgencia INTO @Cuentas
            FROM Cuentas.Cuenta c
            CROSS APPLY (
                SELECT TOP (1) sc.MesesInactividad
                FROM ProductosFinancieros.SubProductoCondicion sc
                WHERE sc.IdSubProducto=c.IdSubProducto AND sc.Estado IN ('Vigente','Programada')
                  AND sc.VigenciaDesde<=:fecha
                  AND (sc.VigenciaHasta IS NULL OR sc.VigenciaHasta>=:fecha)
                ORDER BY sc.VigenciaDesde DESC,sc.IdCondicion DESC
            ) condicion
            OUTER APPLY (
                SELECT TOP (1) e.FechaEvento
                FROM Cuentas.CuentaEvento e
                WHERE e.IdCuenta=c.IdCuenta AND e.TipoEvento='Reactivacion'
                ORDER BY e.FechaEvento DESC,e.IdCuentaEvento DESC
            ) reactivacion
            WHERE c.Estado='Activa' AND condicion.MesesInactividad>0
              AND CAST(COALESCE(c.FechaUltimoMovimientoCliente,c.FechaActivacion,c.FechaApertura) AS date)
                  <= DATEADD(month,-condicion.MesesInactividad,CAST(:fecha AS date))
              AND (reactivacion.FechaEvento IS NULL OR CAST(reactivacion.FechaEvento AS date)
                  <= DATEADD(month,-condicion.MesesInactividad,CAST(:fecha AS date)));

            INSERT Cuentas.CuentaEvento
                (IdCuenta,TipoEvento,EstadoAnterior,EstadoActual,Detalle,RealizadoPor,IdAgencia)
            SELECT IdCuenta,'Inactivacion','Activa','Inactiva',N'Inactividad de la cuenta',0,IdAgencia
            FROM @Cuentas;
            SELECT COUNT(*) FROM @Cuentas;
        """),
        {"fecha": fecha},
    ).scalar_one()
    return Conteo(procesados=cambios, modificados=cambios)


def ejecutar() -> Conteo:
    with get_engine("cooperativa").begin() as conn:
        resultado = inactivar_cuentas(conn, hoy())
    if resultado.modificados:
        audit.registrar(
            audit.EventoAuditoria(
                accion="CTA_INACTIVACION",
                tabla="Cuentas.Cuenta",
                id_registro=None,
                resultado="Exitoso",
                usuario=None,
                ip=None,
                descripcion=f"Cuentas inactivadas por la tarea: {resultado.modificados}",
            )
        )
    return resultado
