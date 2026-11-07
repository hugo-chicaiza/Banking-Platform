"""TRX-01: integración contra BD de PRUEBA (rollback)."""

from collections.abc import Iterator

import pytest
from sqlalchemy import Connection

from app.modules.transacciones import repository as repo
from tests.caja_bd import (
    SIN_BD,
    conexion_de_prueba,
)

pytestmark = SIN_BD


@pytest.fixture
def conn() -> Iterator[Connection]:
    yield from conexion_de_prueba()


def test_trx01_listado_con_alcance(conn: Connection) -> None:
    filas, total = repo.listar_transacciones(
        conn,
        {"alcance": "001", "estado": "Completada"},
        ("idTransaccion", "desc"),
        0,
        5,
    )
    assert len(filas) <= 5 and total >= len(filas)
