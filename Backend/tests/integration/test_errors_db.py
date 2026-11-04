"""Traducción de errores con mensajes reales de SQL Server.

Usa una tabla temporal (#), que vive solo en esta conexión: no toca tablas compartidas.
Se omite si no hay BD configurada (por ejemplo en el CI).
"""

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.api.errors import traducir_error_bd
from app.core.config.settings import get_settings
from app.core.database.db import get_engine

pytestmark = pytest.mark.skipif(
    not get_settings().cooperativa_db_server, reason="CooperativaDB no configurada"
)


@pytest.fixture
def conn():
    with get_engine("cooperativa").connect() as c:
        c.execute(
            text(
                "CREATE TABLE #Unicos (Clave int CONSTRAINT UQ_Unicos UNIQUE, Otro int);"
                "CREATE UNIQUE INDEX IX_Unicos_Otro ON #Unicos (Otro);"
                "INSERT INTO #Unicos VALUES (51234, 1);"
            )
        )
        yield c
        c.rollback()


@pytest.mark.parametrize(
    "insercion",
    [
        "INSERT INTO #Unicos VALUES (51234, 2)",  # UNIQUE KEY: 2627
        "INSERT INTO #Unicos VALUES (7, 1)",  # índice único: 2601
    ],
)
def test_unique_real_se_traduce_a_409(conn, insercion):
    with pytest.raises(DBAPIError) as error:
        conn.execute(text(insercion))

    traducido = traducir_error_bd(error.value)

    assert traducido.status_code == 409
    detalle: Any = traducido.detail
    assert detalle["code"] == "REGISTRO_DUPLICADO"
