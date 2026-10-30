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


def test_productos_activos_ordenados_y_filtrados_por_tipo(conn):
    productos = repository.listar_productos(conn)
    claves = [
        (p["tipo_producto"].casefold(), p["nombre_producto"].casefold())
        for p in productos
    ]
    assert claves == sorted(claves)

    for producto in productos:
        if producto["tipo_producto"] == "Cuenta":
            assert producto["monto_apertura_minimo"] is not None
            assert producto["tipo_cuenta"] in {"Corriente", "Ahorro"}
            assert producto["id_tipo_credito"] is None
            assert producto["id_red"] is None
        elif producto["tipo_producto"] == "Tarjeta":
            assert producto["id_red"] is not None
            assert producto["monto_apertura_minimo"] is None
            assert producto["id_tipo_credito"] is None
            assert producto["tipo_cuenta"] is None
        else:
            assert producto["tipo_producto"] == "Credito"
            assert producto["id_tipo_credito"] is not None
            assert producto["monto_apertura_minimo"] is None
            assert producto["id_red"] is None
            assert producto["tipo_cuenta"] is None

    for tipo in ("Cuenta", "Tarjeta", "Credito"):
        filtrados = repository.listar_productos(conn, tipo)
        assert all(p["tipo_producto"] == tipo for p in filtrados)
        assert filtrados == [p for p in productos if p["tipo_producto"] == tipo]
