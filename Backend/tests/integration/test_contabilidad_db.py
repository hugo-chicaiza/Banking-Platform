"""Verifica el SQL real de CON-01 / CON-02 contra CooperativaDB (solo lectura).

Usa el calendario 2026 ya cargado: 1-ene feriado, 2-ene viernes, 3 y 4-ene fin de
semana, 5-ene lunes. Se omite si no hay BD configurada (por ejemplo en el CI).
"""

from datetime import date, datetime

import pytest

from app.core.config import get_settings
from app.core.db import get_engine
from app.modules.contabilidad import repository

pytestmark = pytest.mark.skipif(
    not get_settings().cooperativa_db_server, reason="CooperativaDB no configurada"
)


@pytest.fixture(scope="module")
def conn():
    with get_engine("cooperativa").connect() as c:
        yield c


def test_dia_habil(conn):
    fila = repository.obtener_por_fecha(conn, date(2026, 1, 2))
    assert fila is not None
    assert fila["es_dia_contable"] is True
    assert fila["es_feriado"] is False


def test_feriado(conn):
    fila = repository.obtener_por_fecha(conn, date(2026, 1, 1))
    assert fila["es_feriado"] is True
    assert fila["es_dia_contable"] is False


def test_fin_de_semana(conn):
    fila = repository.obtener_por_fecha(conn, date(2026, 1, 3))
    assert fila["es_fin_de_semana"] is True
    assert fila["es_dia_contable"] is False


def test_fecha_fuera_del_calendario(conn):
    assert repository.obtener_por_fecha(conn, date(2099, 1, 1)) is None


def test_antes_del_corte_es_el_mismo_dia(conn):
    id_fecha = repository.id_fecha_contable(
        conn, datetime.fromisoformat("2026-01-02T18:59:59")
    )
    assert repository.obtener_por_id(conn, id_fecha)["fecha"] == date(2026, 1, 2)


def test_despues_del_corte_viernes_pasa_al_lunes(conn):
    id_fecha = repository.id_fecha_contable(
        conn, datetime.fromisoformat("2026-01-02T19:00:00")
    )
    assert repository.obtener_por_id(conn, id_fecha)["fecha"] == date(2026, 1, 5)


def test_feriado_pasa_al_siguiente_dia_contable(conn):
    id_fecha = repository.id_fecha_contable(
        conn, datetime.fromisoformat("2026-01-01T10:00:00")
    )
    assert repository.obtener_por_id(conn, id_fecha)["fecha"] == date(2026, 1, 2)


def test_calendario_sin_la_fecha_devuelve_none(conn):
    assert (
        repository.id_fecha_contable(
            conn, datetime.fromisoformat("2099-01-01T10:00:00")
        )
        is None
    )
