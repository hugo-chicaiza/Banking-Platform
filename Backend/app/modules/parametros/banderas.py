"""Dependencia de ruta E0-09, con el contexto verificado de #450."""

from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import Depends
from sqlalchemy import Connection

from app.core.database.db import cooperativa
from app.core.security.auth import Usuario, usuario_actual
from app.modules.parametros.general import verificar_funcion


def requiere_funcion(clave: str):
    def verificar(
        conn: Annotated[Connection, Depends(cooperativa)],
        usuario: Annotated[Usuario | None, Depends(usuario_actual)],
    ) -> None:
        verificar_funcion(
            conn,
            clave,
            datetime.now(ZoneInfo("America/Guayaquil")).date(),
            usuario.agencia() if usuario is not None else None,
        )

    return verificar
