"""CAJ-18 · POST /api/v1/caja/jornadas/{idJornada}/cierre (pruebas sin BD)."""

from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest

from app.modules.caja.router import router
from tests.caja_contexto import (
    BASE,
    ID_SUPERVISOR,
    JORNADA,
    TOTALES,
    Contexto,
    code,
    crear_contexto,
    cuadre,
    jornada,
)


@pytest.fixture
def ctx(monkeypatch: pytest.MonkeyPatch) -> Iterator[Contexto]:
    yield crear_contexto(monkeypatch, router)


def preparar_cierre(ctx: Contexto, **cambios: Any) -> None:
    contado = cuadre(
        SaldoFinalFisico=Decimal("150.00"),
        DiferenciaDinero=Decimal("0.00"),
        EstadoCuadre="CUADRADO",
    )
    estados = iter([JORNADA, jornada(Estado="CERRADA")])
    ctx.fake("obtener_jornada", lambda *a: next(estados))
    ctx.fake("obtener_cuadre_de_jornada", {**contado, **cambios})
    ctx.fake("calcular_totales", TOTALES)
    ctx.fake("cerrar_jornada", True)


def test_caj18_cierra_cuadre_sin_diferencia(ctx: Contexto) -> None:
    preparar_cierre(ctx)
    r = ctx.cliente.post(f"{BASE}/jornadas/55/cierre")
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "CERRADA"
    assert ctx.llamadas["cerrar_jornada"] == [(55,)]


def test_caj18_diferencia_autorizada_cierra(ctx: Contexto) -> None:
    preparar_cierre(
        ctx,
        SaldoFinalFisico=Decimal("149.99"),
        DiferenciaDinero=Decimal("-0.01"),
        IdAutorizadoPor=ID_SUPERVISOR,
    )
    assert ctx.cliente.post(f"{BASE}/jornadas/55/cierre").status_code == 200


@pytest.mark.parametrize(
    ("cambios", "codigo"),
    [
        (
            {
                "SaldoFinalFisico": Decimal("149.99"),
                "DiferenciaDinero": Decimal("-0.01"),
            },
            "CUADRE_NO_AUTORIZADO",
        ),
        ({"SaldoFinalFisico": None}, "CUADRE_PENDIENTE_DE_CONTEO"),
        ({"TotalRetiros": Decimal("10.00")}, "CUADRE_DESACTUALIZADO"),
    ],
)
def test_caj18_reglas(ctx: Contexto, cambios: dict[str, Any], codigo: str) -> None:
    preparar_cierre(ctx, **cambios)
    r = ctx.cliente.post(f"{BASE}/jornadas/55/cierre")
    assert r.status_code == 409
    assert code(r) == codigo
    assert not ctx.llamadas["cerrar_jornada"]


def test_caj18_ya_cerrada_409(ctx: Contexto) -> None:
    ctx.fake("obtener_jornada", jornada(Estado="CERRADA"))
    r = ctx.cliente.post(f"{BASE}/jornadas/55/cierre")
    assert r.status_code == 409
    assert code(r) == "JORNADA_YA_CERRADA"
