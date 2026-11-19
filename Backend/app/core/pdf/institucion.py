"""Datos de la institución para el encabezado de los PDF (E0-18).

Salen del perfil de la entidad (Organizacion.Entidad, E1-01); si todavía no hay perfil
o la base no responde, se usa `COOPERATIVA_NOMBRE` para que el documento igual salga.
"""

import logging
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import Connection
from sqlalchemy.exc import SQLAlchemyError

from app.core.config.settings import get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Institucion:
    nombre: str
    ruc: str | None = None
    sitio_web: str | None = None


def institucion_por_defecto() -> Institucion:
    return Institucion(nombre=get_settings().cooperativa_nombre)


def institucion_actual(conn: Connection) -> Institucion:
    """Nombre comercial (o razón social), RUC y sitio web del perfil de la entidad."""
    from app.modules.organizacion import (
        service as organizacion,
    )  # evita el ciclo core → módulos

    try:
        entidad = organizacion.obtener_entidad(conn)
    except (HTTPException, SQLAlchemyError) as exc:
        logger.warning(
            "pdf: sin perfil de la entidad, se usa COOPERATIVA_NOMBRE tipo=%s",
            type(exc).__name__,
        )
        return institucion_por_defecto()
    return Institucion(
        nombre=entidad.nombre_comercial or entidad.razon_social,
        ruc=entidad.ruc,
        sitio_web=entidad.sitio_web,
    )
