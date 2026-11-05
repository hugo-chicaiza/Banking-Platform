"""Pruebas de integración de CRE-01 y CRE-02 contra CooperativaDB.

Solo lectura. Se omiten si la BD no está configurada (p. ej. en CI sin secretos).
Dependen de la semilla de F-07: tasas de los tipos 1 y 2 vigentes desde 2026-01-01.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.core.config.settings import get_settings
from app.core.database.db import get_engine
from app.modules.creditos import repository, service
from app.modules.creditos.schemas import SimulacionRequest

pytestmark = pytest.mark.skipif(
    not get_settings().cooperativa_db_server,
    reason="CooperativaDB no configurada",
)

HOY = date(2026, 11, 5)
_TIPOS_CALCULO = {"Fijo", "Porcentaje"}


@pytest.fixture(scope="module")
def conn():
    from sqlalchemy import event

    def solo_lectura(conn, cursor, statement, parameters, context, executemany):
        assert statement.lstrip().upper().startswith(("SELECT ", "WITH "))

    def sin_commit(conn):
        raise AssertionError("Las integraciones de créditos no deben hacer commit")

    with get_engine("cooperativa").connect() as c:
        event.listen(c, "before_cursor_execute", solo_lectura)
        event.listen(c, "commit", sin_commit)
        yield c


def test_tasa_vigente_del_tipo_1(conn):
    tasas = repository.tasas_vigentes(conn, 1, HOY)

    assert len(tasas) == 1
    tasa = tasas[0]
    assert tasa["plazo_maximo_meses"] == 48
    assert tasa["tasa_nominal_anual"] == Decimal("0.1600")
    assert tasa["monto_minimo"] == Decimal("500.00")
    assert tasa["monto_maximo"] == Decimal("20000.00")


def test_tasa_vigente_del_tipo_2(conn):
    tasas = repository.tasas_vigentes(conn, 2, HOY)

    assert len(tasas) == 1 and tasas[0]["plazo_maximo_meses"] == 36


def test_tipo_inexistente_no_tiene_tasa(conn):
    assert repository.tasas_vigentes(conn, 999999, HOY) == []


def test_antes_de_la_vigencia_no_hay_tasa(conn):
    assert repository.tasas_vigentes(conn, 1, date(2025, 12, 31)) == []


@pytest.mark.parametrize("consulta", ["seguros_activos", "impuestos_activos"])
def test_rubros_traen_las_columnas_esperadas(conn, consulta):
    filas = getattr(repository, consulta)(conn, 1, HOY)

    for fila in filas:
        assert set(fila) == {
            "id",
            "codigo",
            "nombre",
            "tipo_calculo",
            "valor",
            "obligatorio",
        }
        assert fila["tipo_calculo"] in _TIPOS_CALCULO
        assert isinstance(fila["obligatorio"], bool)


def test_cre01_condiciones_del_tipo_1(conn):
    condiciones = service.obtener_condiciones(
        conn, 1, monto=Decimal(1000), plazo_meses=12, hoy=HOY
    )

    assert condiciones.id_tipo_credito == 1
    assert condiciones.plazo_maximo_meses == 48


def test_cre02_simulacion_completa_contra_la_base(conn):
    datos = SimulacionRequest.model_validate(
        {
            "idTipoCredito": 1,
            "monto": Decimal(1000),
            "plazoMeses": 12,
            "sistemaAmortizacion": "FRANCES",
            "fechaPrimerVencimiento": "2026-12-05",
        }
    )

    simulacion = service.simular(conn, datos, hoy=HOY)

    assert len(simulacion.plan) == 12
    assert simulacion.plan[-1].saldo_final == 0
    assert simulacion.tasa_nominal_anual == Decimal("0.1600")
