"""Vigilante de ventanas (E0-06, M8 AC 17 · P4 AC 13).

Para cada tarea activa con `VentanaEsperadaMin`, si su última ejecución correcta
(`Exitoso` o `Parcial`) es más antigua que la ventana —o nunca corrió—, alerta: línea
`TAREA_SIN_EJECUTAR` en el registro y evento `SIS_TAREA_SIN_EJECUTAR` en la bitácora
(como máximo una vez por tarea y hora).
"""

import logging

from sqlalchemy import text

from app.core.database.db import get_engine
from app.core.security import audit
from app.core.tareas.ejecutor import Conteo

logger = logging.getLogger(__name__)

_ATRASADAS = """
SELECT t.Codigo, t.VentanaEsperadaMin,
       DATEDIFF(minute, MAX(e.FinUTC), SYSUTCDATETIME()) AS MinutosDesdeUltima
FROM Sistema.Tarea t
LEFT JOIN Sistema.TareaEjecucion e
  ON e.Codigo = t.Codigo AND e.Resultado IN ('Exitoso', 'Parcial')
WHERE t.Estado = 'A' AND t.VentanaEsperadaMin IS NOT NULL
  -- una alerta por tarea y hora como máximo (el vigilante corre cada 5 minutos)
  AND NOT EXISTS (
    SELECT 1 FROM Auditoria.Auditoria a
    WHERE a.CodigoEvento = 'SIS_TAREA_SIN_EJECUTAR' AND a.IDRegistro = t.Codigo
      AND a.FechaHoraUTC > DATEADD(minute, -60, SYSUTCDATETIME()))
GROUP BY t.Codigo, t.VentanaEsperadaMin
"""


def tareas_atrasadas() -> list[tuple[str, int, int | None]]:
    with get_engine("seguridad").connect() as conn:
        filas = conn.execute(text(_ATRASADAS)).all()
    return [
        (str(codigo), int(ventana), None if minutos is None else int(minutos))
        for codigo, ventana, minutos in filas
        if minutos is None or int(minutos) > int(ventana)
    ]


def vigilar() -> Conteo:
    atrasadas = tareas_atrasadas()
    for codigo, ventana, minutos in atrasadas:
        detalle = (
            "nunca corrió" if minutos is None else f"última correcta hace {minutos} min"
        )
        logger.error(
            "TAREA_SIN_EJECUTAR codigo=%s ventana=%d %s", codigo, ventana, detalle
        )
        audit.registrar(
            audit.EventoAuditoria(
                accion="SIS_TAREA_SIN_EJECUTAR",
                tabla="Sistema.Tarea",
                id_registro=codigo,
                resultado="Fallido",
                usuario=None,
                ip=None,
                descripcion=f"tarea={codigo} ventana={ventana} min; {detalle}",
                canal="SISTEMA",
            )
        )
    return Conteo(procesados=len(atrasadas), modificados=len(atrasadas))
