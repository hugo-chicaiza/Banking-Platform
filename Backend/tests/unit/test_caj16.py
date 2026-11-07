"""CAJ-16 · PUT /api/v1/caja/jornadas/{idJornada}/cuadre/conteo (pruebas sin BD)."""

from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest

from app.modules.caja.router import router
from tests.caja_contexto import (
    BASE,
    CUADRE,
    JORNADA,
    TOTALES,
    Contexto,
    code,
    crear_contexto,
    cuadre,
)


@pytest.fixture
def ctx(monkeypatch: pytest.MonkeyPatch) -> Iterator[Contexto]:
    yield crear_contexto(monkeypatch, router)


def test_caj16_conteo_con_faltante(ctx: Contexto) -> None:
    ctx.fake("obtener_jornada", JORNADA)
    ctx.fake("obtener_cuadre_de_jornada", CUADRE)
    ctx.fake("calcular_totales", TOTALES)
    ctx.fake("registrar_conteo", True)
    ctx.fake(
        "obtener_cuadre",
        cuadre(
            SaldoFinalFisico=Decimal("149.99"),
            DiferenciaDinero=Decimal("-0.01"),
            EstadoCuadre="FALTANTE",
        ),
    )
    r = ctx.cliente.put(
        f"{BASE}/jornadas/55/cuadre/conteo", json={"saldoFinalFisico": 149.99}
    )
    assert r.status_code == 200, r.text
    assert r.json()["estadoCuadre"] == "FALTANTE"
    (_id, _tot, fisico, diferencia, estado, _obs) = ctx.llamadas["registrar_conteo"][0]
    assert fisico == Decimal("149.99")
    assert diferencia == Decimal("-0.01")
    assert estado == "FALTANTE"


@pytest.mark.parametrize(
    ("fila", "existente", "status", "codigo"),
    [
        (JORNADA, None, 404, "CUADRE_NO_ENCONTRADO"),
        (JORNADA, {**CUADRE, "IdAutorizadoPor": 9}, 409, "CUADRE_YA_CERRADO"),
        ({**JORNADA, "Estado": "CERRADA"}, CUADRE, 409, "CUADRE_YA_CERRADO"),
        ({**JORNADA, "Estado": "CANCELADA"}, CUADRE, 409, "JORNADA_CANCELADA"),
    ],
)
def test_caj16_reglas(
    ctx: Contexto, fila: Any, existente: Any, status: int, codigo: str
) -> None:
    ctx.fake("obtener_jornada", fila)
    ctx.fake("obtener_cuadre_de_jornada", existente)
    ctx.fake("calcular_totales", TOTALES)
    ctx.fake("registrar_conteo", True)
    r = ctx.cliente.put(
        f"{BASE}/jornadas/55/cuadre/conteo", json={"saldoFinalFisico": 1}
    )
    assert r.status_code == status
    assert code(r) == codigo


def test_caj16_fisico_negativo_400(ctx: Contexto) -> None:
    r = ctx.cliente.put(
        f"{BASE}/jornadas/55/cuadre/conteo", json={"saldoFinalFisico": -0.01}
    )
    assert r.status_code == 400
