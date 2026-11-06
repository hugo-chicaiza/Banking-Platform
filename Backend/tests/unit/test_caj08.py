"""CAJ-08 · GET /api/v1/caja/jornadas/{idJornada}/dotaciones (pruebas sin BD)."""

from collections.abc import Iterator

import pytest

from app.modules.caja.router import router
from tests.caja_contexto import (
    BASE,
    DOTACION,
    JORNADA,
    Contexto,
    crear_contexto,
    jornada,
)


@pytest.fixture
def ctx(monkeypatch: pytest.MonkeyPatch) -> Iterator[Contexto]:
    yield crear_contexto(monkeypatch, router)


def test_caj08_lista_dotaciones(ctx: Contexto) -> None:
    ctx.fake("obtener_jornada", JORNADA)
    ctx.fake("listar_dotaciones", [DOTACION])
    r = ctx.cliente.get(f"{BASE}/jornadas/55/dotaciones")
    assert r.status_code == 200
    assert r.json()[0]["idDotacionCaja"] == 801
    assert r.json()[0]["bovedaBajoMinimo"] is None


def test_caj08_jornada_ajena_404(ctx: Contexto) -> None:
    ctx.fake("obtener_jornada", jornada(IdUsuario=8))
    ctx.fake("listar_dotaciones", [DOTACION])
    r = ctx.cliente.get(f"{BASE}/jornadas/55/dotaciones")
    assert r.status_code == 404
    assert not ctx.llamadas["listar_dotaciones"]
