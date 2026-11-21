"""Conexiones existentes con parametros ocultos, sin cambiar la configuracion global."""

from sqlalchemy import Engine

from app.core.database.db import DbName, get_engine


def motor(base: DbName) -> Engine:
    privado = get_engine(base).execution_options()
    privado.hide_parameters = True
    return privado
