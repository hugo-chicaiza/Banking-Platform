"""TRX-03: integración contra BD de PRUEBA (rollback)."""

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


def test_trx03_consultas_del_reverso(conn: Connection) -> None:
    assert repo.existe_reverso(conn, -1) is False
    assert repo.movimientos_de_transaccion(conn, -1) == []


def test_trx03_reverso_real() -> None:
    pytest.skip(
        "BLOQUEADO: asiento inverso (G-06), numeración del reverso (G-11), "
        "devolución de comisiones y vínculo WorkOS → usuario interno"
    )
