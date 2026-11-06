"""CAJ-05: integración contra BD de PRUEBA (rollback)."""

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


def test_caj05_detalle(conn: Connection) -> None:
    assert repo.obtener_jornada(conn, -1) is None
    assert repo.obtener_jornada(conn, -1, bloquear=True) is None
