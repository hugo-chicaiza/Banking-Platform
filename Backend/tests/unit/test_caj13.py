"""CAJ-13 · POST /api/v1/caja/jornadas/{idJornada}/cuadre (pruebas sin BD)."""

from collections.abc import Iterator
from typing import Any

import pytest

from app.modules.caja.router import router
from tests.caja_contexto import (
    BASE,
    CUADRE,
    ID_CAJERO,
    JORNADA,
    TOTALES,
    Contexto,
    code,
    crear_contexto,
)


@pytest.fixture
def ctx(monkeypatch: pytest.MonkeyPatch) -> Iterator[Contexto]:
    yield crear_contexto(monkeypatch, router)


def test_caj13_genera_cuadre_pendiente(ctx: Contexto) -> None:
    ctx.fake("obtener_jornada", JORNADA)
    ctx.fake("obtener_cuadre_de_jornada", None)
    ctx.fake("calcular_totales", TOTALES)
    ctx.fake("id_fecha_contable", 20261104)
    ctx.fake("insertar_cuadre", 70)
    ctx.fake("obtener_cuadre", CUADRE)
    r = ctx.cliente.post(f"{BASE}/jornadas/55/cuadre", json={})
    assert r.status_code == 201, r.text
    cuerpo = r.json()
    assert cuerpo["estadoCuadre"] == "PENDIENTE"
    assert cuerpo["saldoEsperado"] == 150.0
    assert cuerpo["saldoFinalFisico"] is None
    assert ctx.llamadas["insertar_cuadre"][0][:2] == (55, ID_CAJERO)


@pytest.mark.parametrize(
    ("fila", "existente", "codigo"),
    [
        (JORNADA, CUADRE, "CUADRE_YA_EXISTE"),
        ({**JORNADA, "Estado": "CANCELADA"}, None, "JORNADA_CANCELADA"),
        ({**JORNADA, "Estado": "CERRADA"}, None, "JORNADA_NO_ABIERTA"),
    ],
)
def test_caj13_conflictos_409(
    ctx: Contexto, fila: Any, existente: Any, codigo: str
) -> None:
    ctx.fake("obtener_jornada", fila)
    ctx.fake("obtener_cuadre_de_jornada", existente)
    ctx.fake("insertar_cuadre", 70)
    r = ctx.cliente.post(f"{BASE}/jornadas/55/cuadre", json={})
    assert r.status_code == 409
    assert code(r) == codigo
    assert not ctx.llamadas["insertar_cuadre"]
