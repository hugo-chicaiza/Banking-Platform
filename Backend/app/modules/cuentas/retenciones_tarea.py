from sqlalchemy import text

from app.core.database.db import get_engine
from app.core.tareas.ejecutor import Conteo, TareaRechazada
from app.modules.aprobaciones.auditoria import ContextoAuditoria, encolar
from app.modules.contabilidad.repository import obtener_por_id
from app.modules.contabilidad.service import ahora_ecuador, resolver_id_fecha_contable
from app.modules.cuentas import retenciones as r


def liberar_vencidas() -> Conteo:
    engine = get_engine("cooperativa")
    conteo = Conteo()
    with engine.connect() as conn:
        id_fecha = resolver_id_fecha_contable(conn, ahora_ecuador())
        calendario = obtener_por_id(conn, id_fecha)
        if calendario is None:
            raise TareaRechazada("No se pudo determinar la fecha contable.")
        candidatos = conn.execute(
            text("""
            SELECT IdRetencion, IdCuenta FROM Cuentas.Retencion
            WHERE Estado='Activa' AND Origen='Manual' AND FechaFin<=:fecha
            ORDER BY IdCuenta, IdRetencion
        """),
            {"fecha": calendario["fecha"]},
        ).all()

    for id_retencion, id_cuenta in candidatos:
        with engine.begin() as conn:
            fila = r.cuenta(conn, id_cuenta)
            ret = r.retencion(conn, id_retencion, id_cuenta)
            conteo.procesados += 1
            if ret["Estado"] != "Activa":
                continue
            r.liberar_retencion(
                conn,
                fila,
                ret,
                ret["CreadoPor"],
                "Vencimiento de la retención",
                clave=f"CTA-LIBERACION-AUTO:{id_retencion}",
            )
            encolar(
                conn,
                "CTA_LIBERACION",
                None,
                None,
                fila["IdAgencia"],
                ContextoAuditoria(canal="TAREA"),
                {"motivo": "Vencimiento"},
                tabla="Cuentas.Retencion",
                objetivo=str(id_retencion),
            )
            conteo.modificados += 1

    with engine.connect() as conn:
        if conn.execute(
            text("SELECT TOP(1) 1 FROM Cuentas.vw_RetenidoDescuadrado")
        ).scalar():
            raise TareaRechazada(
                "El saldo retenido difiere de la suma de retenciones activas."
            )
    return conteo
