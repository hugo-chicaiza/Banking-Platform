"""CAJ-05 · GET /api/v1/caja/jornadas/{idJornada} (pruebas sin BD)."""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest

from app.modules.caja.router import router
from app.modules.caja.schemas import a_ecuador
from tests.caja_contexto import (
    BASE,
    ID_CAJERO,
    ID_SUPERVISOR,
    JORNADA,
    Contexto,
    code,
    crear_contexto,
)


@pytest.fixture
def ctx(monkeypatch: pytest.MonkeyPatch) -> Iterator[Contexto]:
    yield crear_contexto(monkeypatch, router)


def test_caj05_cajero_ve_su_jornada(ctx: Contexto) -> None:
    ctx.fake("obtener_jornada", JORNADA)
    r = ctx.cliente.get(f"{BASE}/jornadas/55")
    assert r.status_code == 200
    assert r.json()["idUsuario"] == ID_CAJERO


@pytest.mark.parametrize(
    ("roles", "id_interno", "fila"),
    [
        (("CAJERO",), 8, JORNADA),  # de otro cajero
        (("SUPERVISOR",), ID_SUPERVISOR, {**JORNADA, "IdAgencia": "002"}),
        (("CONTADOR",), None, None),  # no existe
    ],
)
def test_caj05_fuera_de_alcance_o_inexistente_404(
    ctx: Contexto, roles: tuple[str, ...], id_interno: int | None, fila: Any
) -> None:
    ctx.como(*roles, id_interno=id_interno)
    ctx.fake("obtener_jornada", fila)
    r = ctx.cliente.get(f"{BASE}/jornadas/55")
    assert r.status_code == 404
    assert code(r) == "JORNADA_NO_ENCONTRADA"


def test_caj05_contador_ve_cualquier_agencia(ctx: Contexto) -> None:
    ctx.como("CONTADOR", agencia="009")
    ctx.fake("obtener_jornada", JORNADA)
    assert ctx.cliente.get(f"{BASE}/jornadas/55").status_code == 200


@pytest.mark.parametrize("valor", ["0", "abc", "2147483648"])
def test_caj05_id_invalido_400(ctx: Contexto, valor: str) -> None:
    r = ctx.cliente.get(f"{BASE}/jornadas/{valor}")
    assert r.status_code == 400


def test_a_ecuador_interpreta_datetime2_como_hora_local() -> None:
    assert a_ecuador(datetime(2026, 11, 4, 8, 0)).isoformat() == (
        "2026-11-04T08:00:00-05:00"
    )


def test_a_ecuador_convierte_valores_con_zona_sin_doble_conversion() -> None:
    utc = datetime(2026, 11, 4, 13, 0, tzinfo=UTC)
    assert a_ecuador(utc).isoformat() == "2026-11-04T08:00:00-05:00"
    assert a_ecuador(a_ecuador(utc)) == a_ecuador(utc)
