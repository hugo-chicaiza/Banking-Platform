"""CAJ-10: integración contra BD de PRUEBA (rollback)."""

from collections.abc import Iterator

import pytest
from sqlalchemy import Connection

from tests.caja_bd import (
    SIN_BD,
    conexion_de_prueba,
    definicion_de,
)

pytestmark = SIN_BD


@pytest.fixture
def conn() -> Iterator[Connection]:
    yield from conexion_de_prueba()


def test_series_json_formato(conn: Connection) -> None:
    definicion = definicion_de(conn, "Boveda.usp_RegistrarSeriesBilletes")
    assert "OPENJSON" in definicion.upper()
