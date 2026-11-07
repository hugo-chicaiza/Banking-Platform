"""CAJ-10 · POST /api/v1/caja/depositos/{idTransaccion}/series (pruebas sin BD)."""

from collections.abc import Iterator
from typing import Any

import pytest

from app.modules.caja.router import router
from app.modules.transacciones import repository as trx_repo
from tests.caja_contexto import (
    BASE,
    JORNADA,
    TRANSACCION,
    Contexto,
    code,
    crear_contexto,
    error_bd,
)


@pytest.fixture
def ctx(monkeypatch: pytest.MonkeyPatch) -> Iterator[Contexto]:
    yield crear_contexto(monkeypatch, router)


CUERPO_SERIES = {
    "idDenominacion": 5,
    "cantidadDeclarada": 2,
    "series": ["AB1234567", "AB1234568"],
}


def preparar_series(ctx: Contexto) -> None:
    ctx.fake("obtener_transaccion", TRANSACCION, trx_repo)
    ctx.fake("obtener_jornada", JORNADA)
    ctx.fake("registrar_series", None)


def test_caj10_registra_series_204(ctx: Contexto) -> None:
    preparar_series(ctx)
    r = ctx.cliente.post(f"{BASE}/depositos/5001/series", json=CUERPO_SERIES)
    assert r.status_code == 204
    assert r.content == b""
    assert ctx.llamadas["registrar_series"] == [
        (5001, 5, 2, '["AB1234567", "AB1234568"]')
    ]


@pytest.mark.parametrize(
    ("fake", "status", "codigo"),
    [
        (("obtener_transaccion", None, trx_repo), 404, "TRANSACCION_NO_ENCONTRADA"),
        (
            ("obtener_jornada", {**JORNADA, "IdUsuario": 8}),
            404,
            "TRANSACCION_NO_ENCONTRADA",
        ),
        (
            (
                "obtener_transaccion",
                {**TRANSACCION, "TipoTransaccion": "Retiro"},
                trx_repo,
            ),
            409,
            "TRANSACCION_NO_ES_DEPOSITO",
        ),
        (("registrar_series", error_bd(51205)), 422, "DB_51205"),
    ],
)
def test_caj10_reglas(ctx: Contexto, fake: Any, status: int, codigo: str) -> None:
    preparar_series(ctx)
    ctx.fake(*fake)
    r = ctx.cliente.post(f"{BASE}/depositos/5001/series", json=CUERPO_SERIES)
    assert r.status_code == status
    assert code(r) == codigo


@pytest.mark.parametrize(
    "cambio",
    [
        {"series": ["AB1", "AB1"]},
        {"cantidadDeclarada": 3},
        {"series": ["X" * 21, "B"]},
        {"series": ["AB 12", "B"]},
    ],
)
def test_caj10_validacion_400(ctx: Contexto, cambio: dict[str, Any]) -> None:
    r = ctx.cliente.post(
        f"{BASE}/depositos/5001/series", json={**CUERPO_SERIES, **cambio}
    )
    assert r.status_code == 400
