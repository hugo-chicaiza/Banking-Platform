"""Pruebas contra una BD de PRUEBA (nunca producción).

Se activan con BANKING_DB_PRUEBAS=1 y las variables de conexión del .env de pruebas.
Las de esta sección solo leen (metadatos y SELECT) y se ejecutan dentro de una
transacción que se revierte. Las que escriben requieren además
BANKING_DB_ESCRITURA=1 y datos de prueba preparados por el equipo.
"""

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text

from app.core.database.db import get_engine
from app.modules.caja import repository as repo

pytestmark = pytest.mark.skipif(
    os.getenv("BANKING_DB_PRUEBAS") != "1",
    reason="Sin BD de prueba: definir BANKING_DB_PRUEBAS=1 (nunca contra producción)",
)
escritura = pytest.mark.skipif(
    os.getenv("BANKING_DB_ESCRITURA") != "1",
    reason="Escritura en BD de prueba desactivada (BANKING_DB_ESCRITURA=1)",
)


@pytest.fixture
def conn() -> Iterator[Connection]:
    with get_engine("cooperativa").connect() as conexion:
        transaccion = conexion.begin()
        try:
            yield conexion
        finally:
            transaccion.rollback()


def _parametros(conn: Connection, objeto: str) -> list[str]:
    return list(
        conn.execute(
            text(
                "SELECT name FROM sys.parameters WHERE object_id = OBJECT_ID(:o)"
                " ORDER BY parameter_id"
            ),
            {"o": objeto},
        ).scalars()
    )


def _definicion(conn: Connection, objeto: str) -> str:
    valor = conn.execute(
        text("SELECT OBJECT_DEFINITION(OBJECT_ID(:o))"), {"o": objeto}
    ).scalar()
    return str(valor or "")


def _columnas(conn: Connection, esquema: str, tabla: str) -> set[str]:
    return set(
        conn.execute(
            text(
                "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS"
                " WHERE TABLE_SCHEMA = :e AND TABLE_NAME = :t"
            ),
            {"e": esquema, "t": tabla},
        ).scalars()
    )


def test_caj01_consulta_cajas(conn: Connection) -> None:
    repo.listar_cajas_fisicas(conn, None, True)
