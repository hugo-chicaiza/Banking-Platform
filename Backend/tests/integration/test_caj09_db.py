"""CAJ-09: integración contra BD de PRUEBA (rollback)."""

from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text

from tests.caja_bd import (
    SIN_BD,
    columnas_de,
    conexion_de_prueba,
)

pytestmark = SIN_BD


@pytest.fixture
def conn() -> Iterator[Connection]:
    yield from conexion_de_prueba()


def test_columnas_denominacion(conn: Connection) -> None:
    columnas = columnas_de(conn, "Catalogo", "Denominacion")
    assert {"IdDenominacion", "Valor"} <= columnas, columnas


def test_tipos_movimiento_caja_configurados(conn: Connection) -> None:
    filas = conn.execute(
        text("SELECT Codigo, Naturaleza FROM Caja.TipoMovimientoCaja")
    ).all()
    assert filas, "Caja.TipoMovimientoCaja está vacía"


def test_deposito_real() -> None:
    pytest.skip(
        "BLOQUEADO: G-06 (plantilla contable), G-11 (numeración), canal de "
        "ventanilla y vínculo WorkOS → usuario interno"
    )
