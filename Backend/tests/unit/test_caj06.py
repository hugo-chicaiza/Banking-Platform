"""CAJ-06 · POST /api/v1/caja/jornadas/{idJornada}/cancelacion (pruebas sin BD)."""

from collections.abc import Iterator
from typing import Any

import pytest

from app.modules.caja.router import router
from tests.caja_contexto import (
    BASE,
    JORNADA,
    Contexto,
    code,
    crear_contexto,
    jornada,
)


@pytest.fixture
def ctx(monkeypatch: pytest.MonkeyPatch) -> Iterator[Contexto]:
    yield crear_contexto(monkeypatch, router)


def test_caj06_cancela_jornada_sin_movimientos(ctx: Contexto) -> None:
    ctx.como("SUPERVISOR")
    estados = iter([JORNADA, jornada(Estado="CANCELADA")])
    ctx.fake("obtener_jornada", lambda *a: next(estados))
    ctx.fake("jornada_tiene_actividad", False)
    ctx.fake("cancelar_jornada", True)
    r = ctx.cliente.post(
        f"{BASE}/jornadas/55/cancelacion", json={"motivo": "Apertura por error"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "CANCELADA"
    assert ctx.llamadas["cancelar_jornada"] == [(55, "Apertura por error")]
    assert ctx.resultado_auditoria() == "Exitoso"


@pytest.mark.parametrize(
    ("fila", "actividad", "status", "codigo"),
    [
        (JORNADA, True, 409, "JORNADA_CON_MOVIMIENTOS"),
        ({**JORNADA, "Estado": "CERRADA"}, False, 409, "JORNADA_NO_ABIERTA"),
        ({**JORNADA, "IdAgencia": "002"}, False, 404, "JORNADA_NO_ENCONTRADA"),
        (None, False, 404, "JORNADA_NO_ENCONTRADA"),
    ],
)
def test_caj06_reglas(
    ctx: Contexto, fila: Any, actividad: bool, status: int, codigo: str
) -> None:
    ctx.como("SUPERVISOR")
    ctx.fake("obtener_jornada", fila)
    ctx.fake("jornada_tiene_actividad", actividad)
    ctx.fake("cancelar_jornada", True)
    r = ctx.cliente.post(f"{BASE}/jornadas/55/cancelacion", json={"motivo": "x"})
    assert r.status_code == status
    assert code(r) == codigo
    assert not ctx.llamadas["cancelar_jornada"]


@pytest.mark.parametrize("cuerpo", [{}, {"motivo": "   "}, {"motivo": "x" * 501}])
def test_caj06_motivo_obligatorio_400(ctx: Contexto, cuerpo: dict[str, Any]) -> None:
    ctx.como("SUPERVISOR")
    r = ctx.cliente.post(f"{BASE}/jornadas/55/cancelacion", json=cuerpo)
    assert r.status_code == 400


def test_caj06_cajero_403(ctx: Contexto) -> None:
    r = ctx.cliente.post(f"{BASE}/jornadas/55/cancelacion", json={"motivo": "x"})
    assert r.status_code == 403
