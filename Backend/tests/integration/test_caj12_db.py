"""CAJ-12: integración contra BD de PRUEBA (rollback)."""

from collections.abc import Iterator

import pytest
from sqlalchemy import Connection

from app.modules.caja import repository as repo
from tests.caja_bd import (
    SIN_BD,
    conexion_de_prueba,
)

pytestmark = SIN_BD


@pytest.fixture
def conn() -> Iterator[Connection]:
    yield from conexion_de_prueba()


def test_caj12_movimientos(conn: Connection) -> None:
    repo.listar_movimientos(conn, -1, ("fechaHora", "asc"), 0, 5)
