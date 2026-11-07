"""CAJ-03: integración contra BD de PRUEBA (rollback)."""

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection

from app.modules.caja import repository as repo
from tests.caja_bd import (
    SIN_BD,
    conexion_de_prueba,
    escritura,
)

pytestmark = SIN_BD


@pytest.fixture
def conn() -> Iterator[Connection]:
    yield from conexion_de_prueba()


def test_caj03_consultas_de_apertura(conn: Connection) -> None:
    repo.cajero_asignado(conn, -1, "000")
    assert repo.jornada_abierta_de_usuario(conn, -1) is None
    assert repo.jornada_abierta_de_caja(conn, -1) is None


@escritura
def test_caj03_apertura_y_rollback(conn: Connection) -> None:
    """Requiere un cajero asignado y una caja libre de prueba en las variables
    BANKING_PRUEBA_CAJERO y BANKING_PRUEBA_CAJA."""
    cajero = int(os.environ["BANKING_PRUEBA_CAJERO"])
    caja = repo.obtener_caja_fisica(conn, int(os.environ["BANKING_PRUEBA_CAJA"]))
    assert caja is not None
    id_jornada = repo.insertar_jornada(
        conn, cajero, caja["IdCajaFisica"], caja["IdAgencia"], 0, "prueba"
    )
    fila = repo.obtener_jornada(conn, id_jornada)
    assert fila is not None and fila["Estado"] == "ABIERTA"
