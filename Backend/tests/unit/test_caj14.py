"""CAJ-14 · GET /api/v1/caja/jornadas/{idJornada}/cuadre (pruebas sin BD)."""

from collections.abc import Iterator
from decimal import Decimal

import pytest

from app.modules.caja.router import router
from app.modules.caja.service import (
    estado_por_diferencia,
    saldo_esperado,
)
from tests.caja_contexto import (
    BASE,
    CUADRE,
    JORNADA,
    Contexto,
    code,
    crear_contexto,
)


@pytest.fixture
def ctx(monkeypatch: pytest.MonkeyPatch) -> Iterator[Contexto]:
    yield crear_contexto(monkeypatch, router)


def test_caj14_consulta_cuadre(ctx: Contexto) -> None:
    ctx.como("SUPERVISOR")
    ctx.fake("obtener_jornada", JORNADA)
    ctx.fake("obtener_cuadre_de_jornada", CUADRE)
    r = ctx.cliente.get(f"{BASE}/jornadas/55/cuadre")
    assert r.status_code == 200
    assert r.json()["idCuadreCaja"] == 70
    assert r.json()["fechaHoraCuadre"] == "2026-11-04T17:00:00-05:00"


def test_caj14_sin_cuadre_404(ctx: Contexto) -> None:
    ctx.fake("obtener_jornada", JORNADA)
    ctx.fake("obtener_cuadre_de_jornada", None)
    r = ctx.cliente.get(f"{BASE}/jornadas/55/cuadre")
    assert r.status_code == 404
    assert code(r) == "CUADRE_NO_ENCONTRADO"


def _totales(**cambios: str) -> dict[str, Decimal]:
    base = {
        "SaldoInicial": "100.00",
        "TotalDotaciones": "50.00",
        "TotalDepositos": "30.10",
        "TotalPagos": "0.20",
        "TotalRetiros": "30.00",
        "TotalDevolucionesBoveda": "0.00",
    }
    return {k: Decimal(v) for k, v in {**base, **cambios}.items()}


def test_saldo_esperado_formula_ck_cuadre() -> None:
    assert saldo_esperado(_totales()) == Decimal("150.30")
    assert saldo_esperado(_totales(TotalDevolucionesBoveda="150.30")) == Decimal("0.00")


def test_saldo_esperado_sin_errores_de_coma_flotante() -> None:
    totales = _totales(TotalDepositos="0.10", TotalPagos="0.20", TotalDotaciones="0")
    totales["SaldoInicial"] = Decimal(0)
    totales["TotalRetiros"] = Decimal(0)
    assert saldo_esperado(totales) == Decimal("0.30")


@pytest.mark.parametrize(
    ("diferencia", "estado"),
    [("0.00", "CUADRADO"), ("0.01", "SOBRANTE"), ("-0.01", "FALTANTE")],
)
def test_estado_por_diferencia(diferencia: str, estado: str) -> None:
    assert estado_por_diferencia(Decimal(diferencia)) == estado
