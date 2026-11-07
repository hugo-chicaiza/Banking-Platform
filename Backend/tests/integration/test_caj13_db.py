"""CAJ-13: integración contra BD de PRUEBA (rollback)."""

from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text

from app.modules.caja import repository as repo
from tests.caja_bd import (
    SIN_BD,
    conexion_de_prueba,
    definicion_de,
)

pytestmark = SIN_BD


@pytest.fixture
def conn() -> Iterator[Connection]:
    yield from conexion_de_prueba()


def test_caj13_totales_coinciden_con_el_trigger(conn: Connection) -> None:
    """Calcula los totales de un cuadre existente y los compara con lo guardado.

    Si falla, la regla de calcular_totales no es la de trg_CuadreCaja_Totales.
    """
    fila = conn.execute(
        text(
            "SELECT TOP (1) IdJornadaCaja FROM Caja.CuadreCaja"
            " ORDER BY IdCuadreCaja DESC"
        )
    ).first()
    if fila is None:
        pytest.skip("No hay cuadres en la BD de prueba")
    cuadre = repo.obtener_cuadre_de_jornada(conn, int(fila[0]))
    totales = repo.calcular_totales(conn, int(fila[0]))
    assert cuadre is not None and totales is not None
    for campo, valor in totales.items():
        assert cuadre[campo] == valor, campo


def test_trigger_de_cuadre_existe(conn: Connection) -> None:
    assert definicion_de(conn, "Caja.trg_CuadreCaja_Totales")
