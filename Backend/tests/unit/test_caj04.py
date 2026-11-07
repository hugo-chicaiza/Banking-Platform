"""CAJ-04 · GET /api/v1/caja/jornadas/actual (pruebas sin BD)."""

from collections.abc import Iterator

import pytest

from app.modules.caja.router import router
from tests.caja_contexto import (
    BASE,
    ID_CAJERO,
    JORNADA,
    Contexto,
    code,
    crear_contexto,
)


@pytest.fixture
def ctx(monkeypatch: pytest.MonkeyPatch) -> Iterator[Contexto]:
    yield crear_contexto(monkeypatch, router)


def test_caj04_jornada_actual(ctx: Contexto) -> None:
    ctx.fake("jornada_abierta_de_usuario", JORNADA)
    r = ctx.cliente.get(f"{BASE}/jornadas/actual")
    assert r.status_code == 200
    assert r.json()["idJornadaCaja"] == 55
    assert ctx.llamadas["jornada_abierta_de_usuario"] == [(ID_CAJERO,)]


def test_caj04_sin_jornada_404(ctx: Contexto) -> None:
    ctx.fake("jornada_abierta_de_usuario", None)
    r = ctx.cliente.get(f"{BASE}/jornadas/actual")
    assert r.status_code == 404
    assert code(r) == "SIN_JORNADA_ABIERTA"


def test_caj04_sin_vinculo_403(ctx: Contexto) -> None:
    ctx.id_interno = None
    r = ctx.cliente.get(f"{BASE}/jornadas/actual")
    assert r.status_code == 403
    assert code(r) == "USUARIO_INTERNO_NO_VINCULADO"


def test_caj04_solo_cajero(ctx: Contexto) -> None:
    ctx.como("SUPERVISOR")
    assert ctx.cliente.get(f"{BASE}/jornadas/actual").status_code == 403
