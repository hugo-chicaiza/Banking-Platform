"""CAJ-15: integración contra BD de PRUEBA (rollback)."""

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


def test_codigos_throw_devolucion(conn: Connection) -> None:
    definicion = definicion_de(conn, "Caja.usp_RegistrarDevolucionCaja")
    faltantes = [
        c
        for c in (51104, 51105, 51106, 51107, 51108, 51109, 51110, 51111, 51113)
        if str(c) not in definicion
    ]
    assert not faltantes, faltantes


def test_g09_flujo_conteo_devolucion_conteo_cierre() -> None:
    pytest.skip(
        "BLOQUEADO G-09: falta aprobación de negocio/DBA del flujo "
        "conteo → devolución → nuevo conteo → autorización → cierre y la "
        "definición de trg_CuadreCaja_Totales"
    )
