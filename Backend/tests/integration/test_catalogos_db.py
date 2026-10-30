"""Verifica el SQL real de catálogos contra CooperativaDB (solo lectura).

Se omite si no hay BD configurada (por ejemplo en el CI).
"""

import pytest

from app.core.config import get_settings
from app.core.db import get_engine
from app.modules.catalogos import repository

pytestmark = pytest.mark.skipif(
    not get_settings().cooperativa_db_server, reason="CooperativaDB no configurada"
)


@pytest.fixture(scope="module")
def conn():
    with get_engine("cooperativa").connect() as c:
        yield c


def test_paises_ordenados_por_nombre(conn):
    nombres = [p["nombre_pais"] for p in repository.listar_paises(conn)]
    assert nombres == sorted(nombres, key=str.casefold)


def test_denominaciones_billetes_primero_y_valor_descendente(conn):
    filas = repository.listar_denominaciones(conn)
    claves = [(f["tipo_pieza"] != "Billete", -f["valor"]) for f in filas]
    assert claves == sorted(claves)


def test_tipos_movimiento_caja_ordenados(conn):
    filas = repository.listar_tipos_movimiento_caja(conn)
    claves = [(f["naturaleza"], f["codigo"]) for f in filas]
    assert claves == sorted(claves)


def test_canales_ordenados_por_nombre(conn):
    filas = repository.listar_canales(conn)

    nombres = [f["nombre_canal"] for f in filas]

    assert nombres == sorted(nombres, key=str.casefold)


def test_canales_solo_activos(conn):
    from sqlalchemy import text

    filas = repository.listar_canales(conn)

    total_activos = conn.execute(
        text(
            """
            SELECT COUNT(*)
            FROM Canal.Canal
            WHERE Estado = 'A'
            """
        )
    ).scalar_one()

    assert len(filas) == total_activos
