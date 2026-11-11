"""Regresión del corte en SQL real. Todas las sentencias ejecutadas son SELECT.

No instala la migración. Sin CooperativaDB configurada se omite. Con la función
antigua, tres casos de test_funcion_instalada fallan: no se oculta ese pendiente.
La propuesta se evalúa con una expresión SELECT, no con un ALTER FUNCTION.
"""

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import text

from app.core.config.settings import get_settings
from app.core.database.db import get_engine

pytestmark = pytest.mark.skipif(
    not get_settings().cooperativa_db_server, reason="CooperativaDB no configurada"
)

CASOS = [
    ("2026-01-01T10:00:00.0000000", date(2026, 1, 2)),
    ("2026-11-06T18:59:59.0000000", date(2026, 11, 6)),
    ("2026-11-06T18:59:59.5000000", date(2026, 11, 6)),
    ("2026-11-06T19:00:00.0000000", date(2026, 11, 9)),
    ("2026-11-06T19:05:00.0000000", date(2026, 11, 9)),
    ("2026-11-07T10:00:00.0000000", date(2026, 11, 9)),
    ("2026-11-08T10:00:00.0000000", date(2026, 11, 9)),
    ("2026-11-09T18:59:59.4999999", date(2026, 11, 9)),
    ("2026-11-09T18:59:59.5000000", date(2026, 11, 9)),
    ("2026-11-09T18:59:59.9999999", date(2026, 11, 9)),
    ("2026-11-09T19:00:00.0000000", date(2026, 11, 10)),
    ("2026-11-09T19:00:00.0000001", date(2026, 11, 10)),
    ("2099-01-01T10:00:00.0000000", None),
]


@pytest.fixture(scope="module")
def resultados():
    # Este es el único archivo SQL que se carga; up/down nunca se ejecutan aquí.
    ruta = Path(__file__).resolve().parents[2] / "scripts/sql/ac02/validar_corte.sql"
    with get_engine("cooperativa").connect() as conn:
        filas = conn.execute(text(ruta.read_text(encoding="utf-8"))).mappings().all()
    assert len(filas) == len(CASOS)
    resultado = {}
    for fila in filas:
        # SQL omite .0000000 al convertir a ISO 126. Se normaliza como texto,
        # sin pasar por datetime de Python, que perdería el séptimo decimal.
        segundos, _, fraccion = fila["Instante"].partition(".")
        resultado[f"{segundos}.{fraccion.ljust(7, '0')}"] = fila
    assert len(resultado) == len(CASOS)
    return resultado


@pytest.mark.parametrize(("instante", "esperado"), CASOS)
def test_propuesta_sin_modificar_funcion(resultados, instante, esperado):
    fila = resultados[instante]
    assert fila["Esperado"] == esperado
    assert fila["ResultadoPropuesto"] == esperado


@pytest.mark.parametrize(("instante", "esperado"), CASOS)
def test_funcion_instalada(resultados, instante, esperado):
    assert resultados[instante]["ResultadoActual"] == esperado, (
        "La función SQL instalada no cumple el corte exacto. Revisar la migración "
        "de AC-02 y el calendario; esta prueba nunca aplica correcciones."
    )
