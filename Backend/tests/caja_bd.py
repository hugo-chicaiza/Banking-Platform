"""Apoyo de pruebas contra una BD de PRUEBA (nunca producción).

Se activan con BANKING_DB_PRUEBAS=1. Todo corre dentro de una transacción que se
revierte; las que escriben exigen además BANKING_DB_ESCRITURA=1.
"""

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text

from app.core.database.db import get_engine

SIN_BD = pytest.mark.skipif(
    os.getenv("BANKING_DB_PRUEBAS") != "1",
    reason="Sin BD de prueba: definir BANKING_DB_PRUEBAS=1 (nunca contra producción)",
)
escritura = pytest.mark.skipif(
    os.getenv("BANKING_DB_ESCRITURA") != "1",
    reason="Escritura en BD de prueba desactivada (BANKING_DB_ESCRITURA=1)",
)


def conexion_de_prueba() -> Iterator[Connection]:
    with get_engine("cooperativa").connect() as conexion:
        transaccion = conexion.begin()
        try:
            yield conexion
        finally:
            transaccion.rollback()


def parametros_de(conn: Connection, objeto: str) -> list[str]:
    return list(
        conn.execute(
            text(
                "SELECT name FROM sys.parameters WHERE object_id = OBJECT_ID(:o)"
                " ORDER BY parameter_id"
            ),
            {"o": objeto},
        ).scalars()
    )


def definicion_de(conn: Connection, objeto: str) -> str:
    valor = conn.execute(
        text("SELECT OBJECT_DEFINITION(OBJECT_ID(:o))"), {"o": objeto}
    ).scalar()
    return str(valor or "")


def columnas_de(conn: Connection, esquema: str, tabla: str) -> set[str]:
    return set(
        conn.execute(
            text(
                "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS"
                " WHERE TABLE_SCHEMA = :e AND TABLE_NAME = :t"
            ),
            {"e": esquema, "t": tabla},
        ).scalars()
    )
