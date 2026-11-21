"""Aplica una bandera solo cuando se alcanza una rama pendiente (HTTP 501)."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Connection
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException

from app.core.api.errors import problema
from app.core.database.db import cooperativa
from app.core.security.auth import Usuario
from app.modules.parametros.banderas import requiere_funcion

logger = logging.getLogger(__name__)


@contextmanager
def funcion_pendiente(
    clave: str, conn: Connection | None = None, usuario: Usuario | None = None
) -> Iterator[None]:
    try:
        yield
    except HTTPException as error:
        if error.status_code != 501:
            raise
        verificar = requiere_funcion(clave)
        try:
            if conn is None:
                # ATM autentica su propia sesión y sus banderas son globales.
                with contextmanager(cooperativa)() as conexion:
                    verificar(conexion, usuario)
            else:
                verificar(conn, usuario)
        except SQLAlchemyError:
            logger.warning("No se pudo consultar la bandera %s", clave)
        # Una bandera activa tampoco sustituye la implementación pendiente.
        raise problema(
            404, "FUNCION_NO_DISPONIBLE", "La funcion no esta disponible."
        ) from None
