"""CAJ-12 · GET /api/v1/caja/jornadas/{idJornada}/movimientos (pruebas sin BD)."""

from collections.abc import Iterator
from datetime import date, datetime

import pytest
from fastapi import HTTPException

from app.core.api.errors import problema
from app.modules.caja.router import router
from app.modules.caja.service import (
    orden_desde_texto,
    rango_fechas,
)
from tests.caja_contexto import (
    BASE,
    JORNADA,
    MOVIMIENTO,
    Contexto,
    crear_contexto,
)


@pytest.fixture
def ctx(monkeypatch: pytest.MonkeyPatch) -> Iterator[Contexto]:
    yield crear_contexto(monkeypatch, router)


def test_caj12_movimientos_paginados(ctx: Contexto) -> None:
    ctx.fake("obtener_jornada", JORNADA)
    ctx.fake("listar_movimientos", ([MOVIMIENTO], 1))
    r = ctx.cliente.get(
        f"{BASE}/jornadas/55/movimientos", params={"page": 2, "pageSize": 10}
    )
    assert r.status_code == 200
    assert r.json()["items"][0]["naturaleza"] == "I"
    assert r.json()["items"][0]["fechaHora"].endswith("-05:00")
    assert ctx.llamadas["listar_movimientos"] == [(55, ("fechaHora", "asc"), 10, 10)]


def test_caj12_orden_invalido_400(ctx: Contexto) -> None:
    ctx.fake("obtener_jornada", JORNADA)
    r = ctx.cliente.get(f"{BASE}/jornadas/55/movimientos", params={"sort": "x,asc"})
    assert r.status_code == 400


def test_orden_desde_texto() -> None:
    permitidos = {"monto": "Monto"}
    assert orden_desde_texto(None, permitidos, ("monto", "asc")) == ("monto", "asc")
    assert orden_desde_texto("monto", permitidos, ("x", "x")) == ("monto", "asc")
    assert orden_desde_texto("monto,desc", permitidos, ("x", "x")) == ("monto", "desc")
    for invalido in ("Monto,asc", "monto;DROP", "monto,DESC"):
        with pytest.raises(HTTPException) as exc:
            orden_desde_texto(invalido, permitidos, ("monto", "asc"))
        assert exc.value.status_code == 400


def test_rango_fechas_hasta_exclusivo() -> None:
    assert rango_fechas(date(2026, 11, 1), date(2026, 11, 1)) == (
        datetime(2026, 11, 1),
        datetime(2026, 11, 2),
    )
    assert rango_fechas(None, None) == (None, None)
    with pytest.raises(type(problema(400, "X", "x"))):
        rango_fechas(date(2026, 11, 2), date(2026, 11, 1))
