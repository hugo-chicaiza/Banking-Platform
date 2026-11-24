"""Disparo local del ejecutor registrado; el bloqueo SQL coordina varias instancias."""

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from app.integrations.workos_client import get_organizacion_id
from app.modules.aprobaciones.tareas import ejecutar

logger = logging.getLogger(__name__)


async def ciclo() -> None:
    from app.modules.aprobaciones.router import servicio

    ultimo_resumen = None
    ultima_anulacion = None
    while True:
        await asyncio.sleep(60)
        try:
            org = get_organizacion_id()
            cola = servicio()
            for codigo in ("APR_RECUPERACION", "APR_AUD_RELEVO"):
                await asyncio.to_thread(ejecutar, cola, org, codigo)
            hoy = datetime.now(ZoneInfo("America/Guayaquil")).date()
            if ultimo_resumen != hoy:
                await asyncio.to_thread(ejecutar, cola, org, "APR_RESUMEN_ANTIGUAS")
                ultimo_resumen = hoy
            if ultima_anulacion != hoy:
                await asyncio.to_thread(ejecutar, cola, org, "CTA_ANULAR_SIN_DEPOSITO")
                ultima_anulacion = hoy
        except (HTTPException, SQLAlchemyError, RuntimeError, ValueError) as error:
            # Nunca imprimir SQL, parametros, sujetos ni el ID de la organizacion.
            logger.warning(
                "aprobaciones: tarea no completada tipo=%s", type(error).__name__
            )


@asynccontextmanager
async def lifespan(_app):
    tarea = asyncio.create_task(ciclo())
    try:
        yield
    finally:
        tarea.cancel()
        with suppress(asyncio.CancelledError):
            await tarea
