"""CAJ-15 · POST /api/v1/caja/jornadas/{idJornada}/devoluciones (pruebas sin BD)."""

from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest

from app.modules.caja.router import router
from tests.caja_contexto import (
    BASE,
    ID_CAJERO,
    ID_SUPERVISOR,
    JORNADA,
    Contexto,
    code,
    crear_contexto,
    cuadre,
    error_bd,
)


@pytest.fixture
def ctx(monkeypatch: pytest.MonkeyPatch) -> Iterator[Contexto]:
    yield crear_contexto(monkeypatch, router)


CUERPO_DEVOLUCION = {
    "idCuadreCaja": 70,
    "idBovedaDestino": 2,
    "autorizadoPor": ID_SUPERVISOR,
    "desglose": [{"idDenominacion": 1, "cantidad": 15}],
}


def preparar_devolucion(ctx: Contexto) -> None:
    ctx.fake("obtener_jornada", JORNADA)
    ctx.fake("autorizador_vigente", True)
    ctx.fake(
        "obtener_cuadre_de_jornada",
        cuadre(SaldoFinalFisico=Decimal("150.00"), DiferenciaDinero=Decimal(0)),
    )
    ctx.fake(
        "registrar_devolucion",
        {"IdDevolucionCaja": 33, "IdMovimientoBoveda": 9100, "SuperaLimiteMaximo": 0},
    )
    ctx.fake(
        "obtener_devolucion",
        {
            "IdDevolucionCaja": 33,
            "IdJornadaCaja": 55,
            "IdCuadreCaja": 70,
            "IdBovedaDestino": 2,
            "Monto": Decimal("150.00"),
            "IdMovimientoBoveda": 9100,
            "Estado": "REGISTRADA",
        },
    )


def test_caj15_devuelve_a_boveda(ctx: Contexto) -> None:
    preparar_devolucion(ctx)
    r = ctx.cliente.post(f"{BASE}/jornadas/55/devoluciones", json=CUERPO_DEVOLUCION)
    assert r.status_code == 201, r.text
    assert r.json()["idDevolucionCaja"] == 33
    assert r.json()["superaLimiteMaximo"] is False
    assert ctx.llamadas["registrar_devolucion"][0][:4] == (55, 70, 2, ID_SUPERVISOR)


@pytest.mark.parametrize(
    ("cambio", "fake", "status", "codigo"),
    [
        ({"idCuadreCaja": 71}, None, 422, "CUADRE_NO_CORRESPONDE"),
        ({"autorizadoPor": ID_CAJERO}, None, 409, "DOBLE_CUSTODIA_VIOLADA"),
        ({}, ("obtener_cuadre_de_jornada", None), 409, "CUADRE_NO_GENERADO"),
        ({}, ("registrar_devolucion", error_bd(51111)), 409, "DB_51111"),
        ({}, ("registrar_devolucion", error_bd(51112)), 422, "DB_51112"),
    ],
)
def test_caj15_reglas(
    ctx: Contexto, cambio: dict[str, Any], fake: Any, status: int, codigo: str
) -> None:
    preparar_devolucion(ctx)
    if fake:
        ctx.fake(*fake)
    r = ctx.cliente.post(
        f"{BASE}/jornadas/55/devoluciones", json={**CUERPO_DEVOLUCION, **cambio}
    )
    assert r.status_code == status
    assert code(r) == codigo
