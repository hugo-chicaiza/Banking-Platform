"""Verifica el SQL real de catálogos contra CooperativaDB (solo lectura).

Se omite si no hay BD configurada (por ejemplo en el CI).
"""

import pytest

from app.core.config.settings import get_settings
from app.core.database.db import get_engine
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


def _contar(conn, sql: str) -> int:
    from sqlalchemy import text

    return conn.execute(text(sql)).scalar_one()


def test_actividades_economicas_solo_activas_y_ordenadas(conn):
    filas = repository.listar_actividades_economicas(conn)

    total = _contar(
        conn, "SELECT COUNT(*) FROM Catalogo.ActividadEconomica WHERE Estado = 'A'"
    )
    assert len(filas) == total
    claves = [
        (f["area_actividad"].casefold(), f["descripcion"].casefold()) for f in filas
    ]
    assert [c[0] for c in claves] == sorted(c[0] for c in claves)


def test_tipos_antecedente_solo_activos_y_categoria_valida(conn):
    filas = repository.listar_tipos_antecedente(conn)

    total = _contar(
        conn, "SELECT COUNT(*) FROM Catalogo.TipoAntecedente WHERE Estado = 'Activo'"
    )
    assert len(filas) == total
    assert {f["categoria"] for f in filas} <= {"EnRevision", "Critico"}
    categorias = [f["categoria"] for f in filas]
    assert categorias == sorted(categorias)


def test_productos_sin_filtro_y_por_cada_tipo(conn):
    todos = repository.listar_productos(conn, None)

    total = _contar(
        conn, "SELECT COUNT(*) FROM ProductosFinancieros.Producto WHERE Estado = 'A'"
    )
    assert len(todos) == total
    por_tipo = 0
    for tipo in ("Cuenta", "Tarjeta", "Credito"):
        filas = repository.listar_productos(conn, tipo)
        por_tipo += len(filas)
        assert {f["tipo_producto"] for f in filas} <= {tipo}
    assert por_tipo == total


def test_productos_campos_que_no_aplican_van_en_null(conn):
    for fila in repository.listar_productos(conn, None):
        tipo = fila["tipo_producto"]
        if tipo != "Cuenta":
            assert fila["monto_apertura_minimo"] is None
            assert fila["tipo_cuenta"] is None
        if tipo != "Credito":
            assert fila["id_tipo_credito"] is None
        if tipo != "Tarjeta":
            assert fila["id_red"] is None
        else:
            assert fila["id_red"] is not None


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
